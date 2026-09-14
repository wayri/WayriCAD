# Local review trust and release policy

WayriCAD 0.6 provides authenticated **local workflow control**, not enterprise identity or a regulated electronic signature system. All catalog data and keys live under the same local OS user's trust boundary.

Passphrases are salted with random 16-byte salts and processed using PBKDF2-HMAC-SHA256 (310,000 iterations). The database stores only salt/hash, role and active state. Application replies/metadata export do not include those hashes or the local HMAC key. Hidden terminal prompts are the default CLI path; named environment variables are available for automation. Never put passwords in a JSON decision, command argument value, shell transcript or shared pipeline.

A local admin creates engineering/supply accounts and can deactivate accounts or revoke decisions. Names are not reassigned; the final active administrator cannot be deactivated. The person controlling the OS/database can ultimately rewrite data or keys. There is no independent identity verification, hardware-protected signing, SSO, network multi-tenant authorization, account lockout service or nonrepudiation claim. Protect the catalog with OS access controls and full-disk encryption as appropriate. Do not expose the loopback application through a remote proxy.

Decision HMACs and catalog hash chains detect ordinary/off-path modifications under that trust model. They are not interchangeable with public-key signatures. Source-document hashes do not prove that the claimed manufacturer authored the document. Reviewer evidence references must be reviewed by your engineering organization.

Release approvals bind engineering context and policy. Ordinary template/layout view changes do not all have the same meaning: engineering inputs, selected variant, catalog epoch, current footprint hashes and policy are bound; view sorting and activity history are excluded. Any missing required approval, unresolved nonwaivable error, stale/expired/revoked/inactive decision or invalid signature blocks a configured controlled release.

Waivers bind one exact warning/unknown finding, scope, role, input fingerprint and expiry. They do not disable a rule globally. Errors cannot be waived. Engineer/supply decisions are separate; an administrator account does not substitute for them. Qualification approvals require a freshly computed matched declared-check report. Scoped alternate decisions bind both recorded revisions and the explicit relationship/evidence, not a global “approved forever” flag.

Read the review report's effective policy. A default policy requiring only engineering approval and BOM errors does **not** implicitly require stock, complete masses, all qualifications, radiation assurance, ERC/DRC or manufacturing release certification. Turn on required gates deliberately; add native KiCad ERC/DRC and other deliverables as separate job-set tasks. Existing pipelines without release_control retain their earlier policies.

Build scenarios never reserve or purchase. A catalog preference change is not a review approval. An intact SHA-256 release manifest is only an integrity result; a FAILED run can be perfectly intact. The local approval is not a signature over every output byte or arbitrary job-set command. Review generated job sets as executable configuration.

Back up source projects, sidecars and the complete closed catalog directory. Keep old plugin versions/source archives alongside release records. Metadata JSON is deliberately insufficient to reconstruct reviewer secrets or captured asset bytes. Concurrent writers and cloud-synced/WAL databases are outside this supported local-workflow model.
