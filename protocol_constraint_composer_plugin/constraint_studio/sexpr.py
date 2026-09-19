"""Small span-preserving s-expression reader, deliberately not a KiCad DRC validator."""
from dataclasses import dataclass, field
import json

class ParseError(ValueError):
    pass

@dataclass
class Node:
    start: int
    end: int
    value: str = ''
    children: list = field(default_factory=list)
    is_list: bool = False
    def head(self):
        return self.children[0].value if self.is_list and self.children else ''
    def atoms(self):
        return [n.value for n in self.children if not n.is_list]
    def find(self, name):
        return [n for n in self.children if n.is_list and n.head() == name]
    def first(self,name):
        v=self.find(name)
        return v[0] if v else None


def parse(text: str) -> list:
    i=0
    length=len(text)
    def fail(message):
        raise ParseError(f'{message} at line {text.count(chr(10),0,i)+1}, offset {i}')
    def trivia():
        nonlocal i
        while i<length:
            if text[i].isspace() or (i==0 and text[i]=='\ufeff'):
                i+=1
            elif text[i]=='#':
                j=text.find('\n',i)
                i=length if j<0 else j+1
            else:
                break
    def read(depth=0):
        nonlocal i
        if depth>150:
            fail('S-expression nesting limit exceeded')
        trivia()
        if i>=length:
            fail('Unexpected end of input')
        start=i
        if text[i]=='(':
            i+=1
            children=[]
            while True:
                trivia()
                if i>=length:
                    fail('Missing closing parenthesis')
                if text[i]==')':
                    i+=1
                    return Node(start,i,children=children,is_list=True)
                children.append(read(depth+1))
        if text[i]==')':
            fail('Unexpected closing parenthesis')
        if text[i] in '\"\'':
            quote=text[i]; i+=1; out=[]
            while i<length:
                c=text[i]; i+=1
                if c==quote:
                    return Node(start,i,''.join(out))
                if c=='\\':
                    if i>=length: fail('Dangling string escape')
                    c=text[i]; i+=1
                    out.append({'n':'\n','r':'\r','t':'\t'}.get(c,c))
                else:
                    out.append(c)
            fail('Unterminated quoted string')
        while i<length and not text[i].isspace() and text[i] not in '()#':
            i+=1
        if i==start:
            fail('Expected token')
        return Node(start,i,text[start:i])
    roots=[]
    while True:
        trivia()
        if i>=length: return roots
        roots.append(read())


def quote(value: str) -> str:
    if '\n' in value or '\r' in value:
        raise ValueError('KiCad rule strings cannot contain newlines')
    return json.dumps(value,ensure_ascii=False)


def expression_quote(value: str) -> str:
    if any(c in value for c in ('\n','\r')):
        raise ValueError('Expression strings must be one line')
    return "'" + value.replace('\\','\\\\').replace("'","\\'") + "'"


def scalar(node, default=''):
    return node.children[1].value if node and len(node.children)>1 else default
