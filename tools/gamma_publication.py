"""Closed dispatch between the original6 and additive completed40 public formats."""
from pathlib import Path
import gamma_showcase as old

def completed(directory):
    try:return old.decode((Path(directory)/'publication.json').read_bytes()).get('kind')=='saved_gamma_complete_publication_v1'
    except (OSError,ValueError):return False

def validate_bundle(directory):
    if completed(directory):
        from gamma_complete_showcase import validate_bundle
        return validate_bundle(directory)
    return old.validate_bundle(directory)

def assemble(source,target,replace=False):
    if completed(source):
        from gamma_complete_showcase import assemble
        return assemble(source,target,replace=replace)
    return old.assemble(source,target,replace=replace)
