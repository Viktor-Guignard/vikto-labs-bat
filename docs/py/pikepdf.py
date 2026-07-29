"""
Implémentation minimale de l'API pikepdf, adossée à PyMuPDF.

Raison d'être : pikepdf dépend de qpdf (C++) et n'existe pas en WebAssembly,
alors que PyMuPDF y est disponible. Ce module expose juste ce que
`analyse_pdf_mail.py` utilise, pour qu'il tourne dans le navigateur sans
être modifié :

    pikepdf.open(path) -> Pdf (context manager) avec .pages
    accès dict/array   -> Dictionary / Array / Name
    héritage           -> MediaBox, CropBox, Resources, Rotate

Les références indirectes sont résolues à la demande, jamais en masse : un
XObject volumineux n'est lu que si le code le consulte vraiment.
"""

import builtins
import re

import pymupdf

__all__ = ["open", "Pdf", "Dictionary", "Array", "Name", "String", "Real", "PdfError"]

# Attributs hérités du nœud /Pages parent (PDF 32000-1, tableau 30).
# TrimBox / BleedBox / ArtBox n'en font volontairement pas partie.
_INHERITABLE = ("/Resources", "/MediaBox", "/CropBox", "/Rotate")

_DELIM = "()<>[]{}/%"


class PdfError(Exception):
    pass


class Name(str):
    """Nom PDF, avec le / initial — str(Name) == '/Separation'."""


class String(str):
    pass


class Real(float):
    """Nombre réel PDF. float suffit ; la classe existe pour l'API."""


class Array(list):
    def __init__(self, items=(), doc=None):
        super().__init__(items)
        self._doc = doc

    def __getitem__(self, i):
        return _resolve(super().__getitem__(i), self._doc)

    def __iter__(self):
        for v in list.__iter__(self):
            yield _resolve(v, self._doc)


class Dictionary(dict):
    def __init__(self, mapping=(), doc=None):
        super().__init__(mapping)
        self._doc = doc

    def __getitem__(self, k):
        return _resolve(super().__getitem__(k), self._doc)

    def get(self, k, default=None):
        if not dict.__contains__(self, k):
            return default
        return self[k]

    def values(self):
        for k in self.keys():
            yield self[k]

    def items(self):
        for k in self.keys():
            yield k, self[k]


class Ref:
    """Référence indirecte « 12 0 R », résolue seulement si on la lit."""

    __slots__ = ("num",)

    def __init__(self, num):
        self.num = num

    def __repr__(self):
        return f"{self.num} 0 R"


def _resolve(value, doc, _depth=0):
    if isinstance(value, Ref) and doc is not None and _depth < 32:
        return _resolve(doc._object(value.num), doc, _depth + 1)
    return value


def _decode_name(raw):
    """#20 -> espace, comme le fait pikepdf."""
    return re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), raw)


class _Parser:
    """Analyseur de la syntaxe objet PDF renvoyée par PyMuPDF."""

    def __init__(self, text, doc):
        self.s = text
        self.i = 0
        self.n = len(text)
        self.doc = doc

    def _skip(self):
        while self.i < self.n:
            c = self.s[self.i]
            if c in " \t\r\n\f\x00":
                self.i += 1
            elif c == "%":
                while self.i < self.n and self.s[self.i] not in "\r\n":
                    self.i += 1
            else:
                return

    def parse(self):
        self._skip()
        if self.i >= self.n:
            return None
        c = self.s[self.i]

        if c == "/":
            return self._name()
        if c == "(":
            return self._literal_string()
        if c == "[":
            return self._array()
        if self.s.startswith("<<", self.i):
            return self._dict()
        if c == "<":
            return self._hex_string()
        if c in "]>}":            # délimiteur fermant orphelin
            self.i += 1
            return None
        return self._bare()

    def _name(self):
        self.i += 1
        start = self.i
        while self.i < self.n and self.s[self.i] not in _DELIM and not self.s[self.i].isspace():
            self.i += 1
        return Name("/" + _decode_name(self.s[start:self.i]))

    def _literal_string(self):
        self.i += 1
        depth = 1
        out = []
        while self.i < self.n:
            c = self.s[self.i]
            if c == "\\":
                self.i += 1
                if self.i < self.n:
                    out.append(self.s[self.i])
                    self.i += 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    self.i += 1
                    break
            out.append(c)
            self.i += 1
        return String("".join(out))

    def _hex_string(self):
        self.i += 1
        start = self.i
        while self.i < self.n and self.s[self.i] != ">":
            self.i += 1
        raw = re.sub(r"\s", "", self.s[start:self.i])
        self.i += 1
        if len(raw) % 2:
            raw += "0"
        try:
            return String(bytes.fromhex(raw).decode("latin-1"))
        except ValueError:
            return String("")

    def _array(self):
        self.i += 1
        items = []
        while self.i < self.n:
            self._skip()
            if self.i < self.n and self.s[self.i] == "]":
                self.i += 1
                break
            before = self.i
            items.append(self.parse())
            if self.i == before:  # sécurité anti-boucle
                self.i += 1
        return Array(self._fold_refs(items), self.doc)

    def _dict(self):
        self.i += 2
        items = []
        while self.i < self.n:
            self._skip()
            if self.s.startswith(">>", self.i):
                self.i += 2
                break
            before = self.i
            items.append(self.parse())
            if self.i == before:
                self.i += 1
        items = self._fold_refs(items)
        d = {}
        for j in range(0, len(items) - 1, 2):
            k = items[j]
            if isinstance(k, Name):
                d[str(k)] = items[j + 1]
        return Dictionary(d, self.doc)

    def _bare(self):
        start = self.i
        while self.i < self.n and self.s[self.i] not in _DELIM and not self.s[self.i].isspace():
            self.i += 1
        tok = self.s[start:self.i]
        if tok == "":
            self.i += 1
            return None
        if tok == "true":
            return True
        if tok == "false":
            return False
        if tok in ("null", "R", "stream", "endobj"):
            return None if tok != "R" else _R_MARKER
        try:
            return int(tok)
        except ValueError:
            pass
        try:
            return float(tok)
        except ValueError:
            return Name("/" + tok) if tok.startswith("/") else String(tok)

    @staticmethod
    def _fold_refs(items):
        """Replie les triplets « num gen R » en objets Ref."""
        out = []
        for v in items:
            if v is _R_MARKER:
                if len(out) >= 2 and isinstance(out[-1], int) and isinstance(out[-2], int):
                    num = out[-2]
                    del out[-2:]
                    out.append(Ref(num))
                continue
            out.append(v)
        return out


class _RMarker:
    def __repr__(self):
        return "R"


_R_MARKER = _RMarker()


class Page(Dictionary):
    """Page PDF, avec l'héritage des attributs du nœud parent."""

    def __init__(self, mapping, doc, xref):
        super().__init__(mapping, doc)
        self.xref = xref

    def _inherited(self, key):
        seen = set()
        node = self
        while node is not None:
            parent = dict.get(node, "/Parent")
            if not isinstance(parent, Ref) or parent.num in seen:
                return None
            seen.add(parent.num)
            node = self._doc._object(parent.num)
            if not isinstance(node, Dictionary):
                return None
            if dict.__contains__(node, key):
                return node[key]
        return None

    def __contains__(self, k):
        if dict.__contains__(self, k):
            return True
        return k in _INHERITABLE and self._inherited(k) is not None

    def get(self, k, default=None):
        if dict.__contains__(self, k):
            return self[k]
        if k in _INHERITABLE:
            v = self._inherited(k)
            if v is not None:
                return v
        return default

    def __getitem__(self, k):
        if dict.__contains__(self, k):
            return super().__getitem__(k)
        if k in _INHERITABLE:
            v = self._inherited(k)
            if v is not None:
                return v
        raise KeyError(k)

    def __setitem__(self, k, v):
        """Écrit la valeur dans le PDF sous-jacent, pas seulement en mémoire.

        Seuls les tableaux de nombres — les boîtes /MediaBox, /TrimBox… — sont
        gérés : c'est le seul type que le moteur réécrit.
        """
        dict.__setitem__(self, k, v)
        if isinstance(v, (list, tuple)):
            corps = " ".join(_pdf_nombre(x) for x in v)
            self._doc._ecrire_cle(self.xref, k, "[ " + corps + " ]")
        else:
            self._doc._ecrire_cle(self.xref, k, str(v))


def _pdf_nombre(x):
    """Formate un nombre en syntaxe PDF, sans notation scientifique."""
    f = float(x)
    return str(int(f)) if f == int(f) else f"{f:.6f}".rstrip("0").rstrip(".")


class Pdf:
    def __init__(self, source):
        # pikepdf.open accepte un chemin, des octets ou un objet fichier.
        if isinstance(source, (bytes, bytearray)):
            self._doc = pymupdf.open(stream=bytes(source), filetype="pdf")
        elif hasattr(source, "read"):
            self._doc = pymupdf.open(stream=source.read(), filetype="pdf")
        else:
            self._doc = pymupdf.open(source)
        self._cache = {}
        self.pages = [
            Page(self._page_dict(i), self, self._doc[i].xref)
            for i in range(self._doc.page_count)
        ]

    # ── résolution d'objets ──────────────────────────────────
    def _object(self, num):
        if num in self._cache:
            return self._cache[num]
        self._cache[num] = None          # coupe les cycles pendant l'analyse
        try:
            src = self._doc.xref_object(num, compressed=False)
        except Exception:
            return None
        val = _Parser(src, self).parse() if src else None
        self._cache[num] = val
        return val

    def _ecrire_cle(self, xref, cle, valeur):
        """Écrit une entrée du dictionnaire d'un objet et invalide le cache."""
        self._doc.xref_set_key(xref, cle.lstrip("/"), valeur)
        self._cache.pop(xref, None)

    def save(self, cible=None, **kwargs):
        """Enregistre le PDF. Accepte un chemin ou un objet fichier."""
        octets = self._doc.tobytes()
        if cible is None:
            return octets
        if hasattr(cible, "write"):
            cible.write(octets)
            return None
        with builtins.open(cible, "wb") as f:
            f.write(octets)
        return None

    def _page_dict(self, index):
        xref = self._doc[index].xref
        obj = self._object(xref)
        return dict(obj) if isinstance(obj, dict) else {}

    # ── context manager ──────────────────────────────────────
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self):
        try:
            self._doc.close()
        except Exception:
            pass

    def __len__(self):
        return len(self.pages)


def open(filename_or_stream, *args, **kwargs):  # noqa: A001 (nom imposé par l'API pikepdf)
    return Pdf(filename_or_stream)
