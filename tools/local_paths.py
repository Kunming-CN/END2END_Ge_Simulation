"""Containment and link checks for the local-only workspace index."""
import os
import stat
from pathlib import Path

def linked(path):
    try:
        info=Path(path).lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0) &
                                              getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024))

def safe_path(path, root):
    root=Path(root).resolve()
    path=Path(os.path.abspath(path))
    try:
        relative=path.relative_to(root)
    except ValueError:
        return False
    current=root
    for component in relative.parts:
        current=current/component
        if linked(current):
            return False
    return path.resolve(strict=False).is_relative_to(root)

def require_safe(path, root):
    if not safe_path(path,root):
        raise ValueError('Linked or escaping local workspace path refused: '+str(path))
