"""Bounded, pure net-name hints. No rates, electrical validation or board writes.

Names and rules are untrusted input. Ambiguous protocol and mate candidates are
reported, never resolved by ordering. Targets are reference hints, not limits;
in particular they cannot validate coupled differential impedance.
"""

from copy import deepcopy
from fnmatch import fnmatchcase
import math
import re


SCHEMA = "wayricad.rlc-protocol-discovery/v1"
MAX_NETS = 10000
MAX_NET_LENGTH = 256
MAX_RULES = 32
MAX_PATTERN_LENGTH = 128

# Local reference provenance mirrors the supported SI families without imports.
_USB_REF = "https://www.ti.com/lit/an/slla414/slla414.pdf"
_CATALOG = [
    ("usb2", "USB 2", True, 90, ("USB2", "USB20"), [_USB_REF]),
    ("usb3", "USB 3", True, 90, ("USB3", "USB30", "USBSS", "SUPERSPEED"), [_USB_REF]),
    ("usb4", "USB4", True, None, ("USB4",), []),
    ("can", "CAN / CAN FD", True, None, ("CAN", "CANFD"),
     ["https://www.ti.com/lit/an/slla270/slla270.pdf"]),
    ("rs485", "RS-485", True, None, ("RS485",), []),
    ("ethernet-mdi", "Ethernet MDI", True, 100, ("ETHERNET", "MDI", "ETH"), []),
    ("rgmii", "Ethernet RGMII", False, 50, ("RGMII",),
     ["https://www.ti.com/lit/ds/symlink/dp83867ir.pdf"]),
    ("sgmii", "Ethernet SGMII", True, 100, ("SGMII",),
     ["https://www.ti.com/lit/ds/symlink/dp83867cs.pdf"]),
    ("10gbase-kr", "Ethernet 10GBASE-KR", True, 100, ("10GBASEKR", "10GBASE-KR"),
     ["https://www.ti.com/lit/ds/symlink/tlk10031.pdf"]),
    ("rf", "RF", False, 50, ("RF",), []),
    ("serdes", "SerDes", True, None, ("SERDES",), []),
    ("fpga-gt", "FPGA GTH / GTY / GTX / GTP transceivers", True, None,
     ("GTH", "GTY", "GTX", "GTP"), []),
    ("lvds", "LVDS", True, 100, ("LVDS",),
     ["https://www.ti.com/lit/ug/snla187/snla187.pdf"]),
    ("pcie", "PCI Express", True, None, ("PCIE", "PCIEXPRESS", "PCI-EXPRESS", "PEX"), []),
    ("sata", "SATA", True, 100, ("SATA",),
     ["https://www.ti.com/product/SN75LVCP601"]),
    ("ddr", "DDR", False, None, ("DDR", "DDR2", "DDR3", "DDR4", "DDR5", "LPDDR", "LPDDR4", "LPDDR5"), []),
    ("i2c", "I2C", False, None, ("I2C", "IIC"), []),
    ("spi", "SPI", False, None, ("SPI", "QSPI"), []),
    ("uart", "UART", False, None, ("UART", "USART"), []),
    ("i2s-tdm", "I2S / TDM", False, None, ("I2S", "TDM"), []),
    ("sdio", "SDIO", False, None, ("SDIO",), []),
    ("parallel-pci", "Parallel PCI", False, None, ("PCI",), []),
    ("parallel-gpio", "Parallel GPIO", False, None, ("GPIO",), []),
    ("m2", "M.2 (interface review required)", False, None, ("M2",), []),
    ("hdmi", "HDMI", True, None, ("HDMI", "TMDS"), []),
    ("displayport", "DisplayPort", True, None, ("DISPLAYPORT", "EDP"), []),
]


def list_profiles():
    """Return fresh JSON-safe logical families; no operating rate is inferred."""
    return [dict(id=key, title=title, differential=diff, target_ohm=target,
                 references=deepcopy(refs), aliases=list(aliases),
                 review_required=key == "m2",
                 limitations=["Net-name hint only; verify endpoint requirements.",
                              "Coupled differential impedance remains unresolved."])
            for key, title, diff, target, aliases, refs in _CATALOG]


def _tokens(value):
    return re.findall(r"[A-Z]+|[0-9]+", value.upper())


def _contains(tokens, alias):
    parts = _tokens(alias)
    return any(tokens[i:i + len(parts)] == parts
               for i in range(len(tokens) - len(parts) + 1))


def _pair_identity(net):
    """Keep hierarchy, lane numbers and instance numbers in the mate key."""
    parts = net.upper().replace("\\", "/").split("/")
    leaf = parts[-1]
    polarity = None
    embedded=re.search(r'(TX|RX)([PN])([0-9]+)$',leaf)
    if embedded:
        polarity='+' if embedded.group(2)=='P' else '-'
        leaf=leaf[:embedded.start()]+embedded.group(1)+'_'+embedded.group(3)
    special = re.search(r"(CAN[0-9]*)[_. -]*([HL])$|(RS[_. -]*485[0-9]*)[_. -]*([AB])$|(?<![A-Z])(DP|DM)$", leaf)
    if embedded:
        pass
    elif special:
        if special.group(1):
            leaf = leaf[:special.start()] + special.group(1)
            polarity = "+" if special.group(2) == "H" else "-"
        elif special.group(3):
            leaf = leaf[:special.start()] + special.group(3)
            polarity = "+" if special.group(4) == "A" else "-"
        else:
            leaf = leaf[:special.start()] + "D"
            polarity = "+" if special.group(5) == "DP" else "-"
    else:
        suffix = re.search(r"(?:[_. -]?)([PN])$|([+-])$", leaf)
        if suffix:
            # A terminal P/N is meaningful only after a separator, number, or
            # familiar differential role (not the final N of SCAN).
            prefix = leaf[:suffix.start()]
            if suffix.group(2) or suffix.start() < len(leaf) - 1 or re.search(r"(?:[0-9]|TX|RX|CLK|DQ|DQS)$", prefix):
                polarity = "+" if (suffix.group(1) == "P" or suffix.group(2) == "+") else "-"
                leaf = prefix
    parts[-1] = leaf
    group = "/".join("_".join(_tokens(part)) for part in parts)
    return group, polarity


def _rules(rules, ids):
    if rules is None:
        return []
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        raise ValueError("rules must be a list of at most %d entries" % MAX_RULES)
    result = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError("Each rule must be an object")
        pattern, kind, key = (rule.get(k) for k in ("pattern", "kind", "profile_id"))
        if not isinstance(pattern, str) or not 1 <= len(pattern) <= MAX_PATTERN_LENGTH:
            raise ValueError("Rule pattern length must be 1..%d" % MAX_PATTERN_LENGTH)
        if kind not in ("wildcard", "regex") or not isinstance(key, str) or key not in ids:
            raise ValueError("Invalid rule kind or unknown profile_id")
        compiled = None
        if kind == "regex":
            # Deliberately small safe subset: no groups, backreferences,
            # alternation or counted repeats. At most one variable repeat
            # avoids combinatorial backtracking, even on bounded inputs.
            if re.search(r"[(){}|]|\\[1-9]|\\[gk]", pattern):
                raise ValueError("Unsupported regex construct")
            unescaped = re.sub(r"\\.", "", pattern)
            if len(re.findall(r"[+*?]", unescaped)) > 1:
                raise ValueError("Regex permits at most one repetition")
            try:
                compiled = re.compile(pattern, re.IGNORECASE | re.ASCII)
            except re.error as exc:
                raise ValueError("Malformed regex: %s" % exc) from exc
        elif pattern.count("[") != pattern.count("]"):
            raise ValueError("Malformed wildcard character class")
        result.append((index, pattern, kind, key, compiled))
    return result


def _one_edit(left, right):
    if len(left) == len(right):
        differences = [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
        if len(differences) == 1:
            return True
        return (len(differences) == 2 and differences[1] == differences[0] + 1
                and left[differences[0]] == right[differences[1]]
                and left[differences[1]] == right[differences[0]])
    if len(left) > len(right):
        left, right = right, left
    if len(right) - len(left) != 1:
        return False
    return any(left == right[:i] + right[i + 1:] for i in range(len(right)))


def discover_protocols(nets, rules=None, min_confidence=0.75):
    """Discover candidates from up to MAX_NETS strings, without reading a board.

    Rules search raw names case-insensitively (wildcards match the whole name).
    Threshold-filtered names remain unclassified. Ambiguities contain a net,
    a reason and all candidate profile IDs or mate names; no winner is forced.
    Invalid or oversized inputs raise ValueError before discovery.
    """
    if isinstance(min_confidence, bool) or not isinstance(min_confidence, (float, int)) or not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be finite and in [0, 1]")
    if isinstance(nets, (str, bytes)):
        raise ValueError("nets must be an iterable of net-name strings")
    names = set()
    try:
        for count, net in enumerate(nets):
            if count >= MAX_NETS:
                raise ValueError("Too many nets")
            if not isinstance(net, str) or not 1 <= len(net) <= MAX_NET_LENGTH or any(ord(c) < 32 for c in net):
                raise ValueError("Invalid net name or net-name length")
            names.add(net)
    except TypeError as exc:
        raise ValueError("nets must be iterable") from exc
    profiles = list_profiles()
    by_id = {p["id"]: p for p in profiles}
    custom = _rules(rules, by_id)
    matches, ambiguities, unclassified = [], [], []
    polarities = {}
    for net in sorted(names):
        group, polarity = _pair_identity(net)
        polarities[net] = polarity
        # Decode familiar compound electrical suffixes before token matching.
        normalized = re.sub(r"CAN([0-9]*)[_. -]*[HL](?=$|[/_. -])", r"CAN\1", net.upper())
        normalized = re.sub(r"RS[_. -]*485([0-9]*)[_. -]*[AB](?=$|[/_. -])", r"RS485\1", normalized)
        normalized=re.sub(r'(?<![A-Z0-9])(GTH|GTY|GTX|GTP)(?=(?:TX|RX))',r'\1_',normalized)
        tokens = _tokens(normalized)
        power = any(t in {"VBUS", "VCC", "VDD", "AVDD", "VBAT", "VREF", "GND", "POWER", "PWR", "VOLTAGE"} for t in tokens)
        power = power or bool(re.search(r"(?:[0-9]+V[0-9]*|(?:^|[^A-Z0-9])V[0-9]+)(?:$|[^A-Z0-9])", net.upper()))
        candidates = {}

        def add(key, confidence, method, evidence):
            if confidence < min_confidence:
                return
            old = candidates.get(key)
            if old:
                old["evidence"].append(evidence)
                if confidence > old["confidence"]:
                    old.update(confidence=confidence, method=method)
                old["review_required"] = old["method"] == "fuzzy" or key == "m2"
                return
            candidates[key] = dict(net=net, profile_id=key, confidence=confidence,
                                   method=method, evidence=[evidence],
                                   differential=by_id[key]["differential"] or (key == "ddr" and polarity is not None),
                                   mate=None, group=group,
                                   review_required=method == "fuzzy" or key == "m2")

        if not power:
            known_words = {a for p in profiles for a in p["aliases"]}
            for profile in profiles:
                for alias in profile["aliases"]:
                    if _contains(tokens, alias):
                        add(profile["id"], 0.95, "tokens", "Token alias: " + alias)
            if _contains(tokens, "USB") and not any(k in candidates for k in ("usb2", "usb3", "usb4")):
                if any(t in {"DP", "DM"} for t in tokens) or ("D" in tokens and polarity):
                    add("usb2", 0.9, "tokens", "USB D+/D- or DP/DM naming")
                elif any(t in {"SS", "SSTX", "SSRX", "SUPERSPEED"} for t in tokens):
                    add("usb3", 0.9, "tokens", "USB SuperSpeed naming (no rate inferred)")
                else:
                    for key in ("usb2", "usb3", "usb4"):
                        add(key, 0.8, "tokens", "USB generation unresolved by name")
            # Specific Ethernet interfaces are not additional MDI evidence.
            if any(k in candidates for k in ("rgmii", "sgmii", "10gbase-kr")):
                candidates.pop("ethernet-mdi", None)
            if _contains(tokens, "PCI-EXPRESS"):
                candidates.pop("parallel-pci", None)
            for profile in profiles:
                for alias in profile["aliases"]:
                    if len(alias) < 5 or not alias.isalpha():
                        continue
                    for token in tokens:
                        if len(token) >= 5 and token not in known_words and _one_edit(token, alias):
                            add(profile["id"], 0.78, "fuzzy", "Possible typo: %s -> %s" % (token, alias))
            for index, pattern, kind, key, compiled in custom:
                if (compiled.search(net) if compiled else fnmatchcase(net.upper(), pattern.upper())):
                    add(key, 1.0, kind, "Rule %d (%s): %s" % (index, kind, pattern))
        if not candidates:
            unclassified.append(net)
        if len(candidates) > 1:
            ambiguities.append(dict(net=net, reason="multiple_profiles", candidates=sorted(candidates)))
            for candidate in candidates.values():
                candidate["review_required"] = True
        matches.extend(candidates[key] for key in sorted(candidates))

    pairs = {}
    for match in matches:
        if match["differential"] and polarities[match["net"]] is not None:
            pairs.setdefault((match["profile_id"], match["group"]), []).append(match)
    for members in pairs.values():
        positive = [m for m in members if polarities[m["net"]] == "+"]
        negative = [m for m in members if polarities[m["net"]] == "-"]
        if len(positive) == len(negative) == 1:
            positive[0]["mate"] = negative[0]["net"]
            negative[0]["mate"] = positive[0]["net"]
        elif len(positive) > 1 or len(negative) > 1:
            for match in members:
                match["review_required"] = True
                ambiguities.append(dict(net=match["net"], reason="multiple_mates",
                                        candidates=sorted(m["net"] for m in members if m is not match)))
    return dict(schema=SCHEMA, profiles=profiles, matches=matches,
                unclassified=unclassified, ambiguities=ambiguities)
