"""Bounded saved-artifact reads and a waveform camera; no publication or workers."""
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat

MAX_BYTES = 16 * 1024 * 1024


def require(ok, message):
    if not ok:
        raise ValueError(message)


def decode(raw):
    def unique(pairs):
        value = {}
        for k, v in pairs:
            require(k not in value, 'Duplicate JSON key: ' + k)
            value[k] = v
        return value
    def finite(token):
        value = float(token)
        require(math.isfinite(value), 'Nonfinite JSON float')
        return value
    def invalid(token):
        raise ValueError('Nonfinite JSON token: ' + token)
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique,
                      parse_float=finite, parse_constant=invalid)


def no_links(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not
                (getattr(info, 'st_file_attributes', 0) & 0x400), 'Linked/reparse path refused')
    return path


def relative(base, name):
    require(type(name) is str and '\\' not in name and ':' not in name, 'Unsafe filename')
    p = PurePosixPath(name)
    require(not p.is_absolute() and p.parts and all(x not in ('.', '..') for x in p.parts)
            and str(p) == name, 'Unsafe relative filename')
    return no_links(Path(base).joinpath(*p.parts))


class Reader:
    def __init__(self, root):
        self.root = no_links(root)
        self.seen = {}

    def raw(self, name, digest=None, size=None):
        path = relative(self.root, name)
        require(path.is_file() and path.stat().st_size <= MAX_BYTES, 'Missing/oversize source: ' + name)
        raw = path.read_bytes()
        require(len(raw) <= MAX_BYTES, 'Source grew beyond bound')
        actual = hashlib.sha256(raw).hexdigest()
        require(digest is None or actual == digest, 'Changed source: ' + name)
        require(size is None or len(raw) == size, 'Changed source size: ' + name)
        require(name not in self.seen or self.seen[name] == actual, 'Source changed during read')
        self.seen[name] = actual
        return raw

    def json(self, name, digest=None):
        return decode(self.raw(name, digest))

    def recheck(self):
        for name, digest in list(self.seen.items()):
            self.raw(name, digest)


def focus_end(t, q):
    """Existing sampled-variation camera, never a full-collection assertion."""
    differences = [abs(b-a) for a, b in zip(q, q[1:])]
    total = sum(differences)
    index = 1
    accumulated = 0.0
    if total:
        for index, difference in enumerate(differences, 1):
            accumulated += difference
            if accumulated >= .995*total:
                break
    edge = t[index]
    return 2*math.ceil((edge+max(10., .2*edge))/2)
