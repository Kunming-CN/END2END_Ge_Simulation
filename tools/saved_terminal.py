"""Per-process reuse of successful terminal inspection; every read rehashes all files."""
from pathlib import Path
import copy
import scenario_workflow as W


class Verifier:
    def __init__(self, root, inspector=None):
        self.root=Path(root); self.inspector=inspector; self._verified={}

    def inspect(self, name):
        directory=W.run_path(name,self.root)
        complete_path=directory/'COMPLETE.json'
        if not complete_path.is_file():return (self.inspector or W.inspect)(name,self.root)
        complete_hash=W.sha(complete_path)
        prior=self._verified.get(name)
        if prior is not None:
            # A terminal authority is immutable for this server lifetime. A
            # rehashed replacement cannot become a new authority on a cache hit.
            W.require(complete_hash==prior['complete_sha256'],'Completed authority changed after verification.')
            W.require(W.sha(directory/'resolved-config.json')==prior['config_sha256'], 'Saved configuration bytes changed.')
            W.require(W.encoded(W.inventory(directory,exclude=('COMPLETE.json','STOP.json')))==W.encoded(prior['artifacts']),
                      'Completed artifact inventory or bytes changed.')
            return copy.deepcopy(prior['receipt'])
        receipt=(self.inspector or W.inspect)(name,self.root)
        W.require(receipt['status'] in W.TERMINAL and receipt.get('verification')=='terminal_artifacts_verified',
                  'Only a successful terminal inspection may be reused.')
        complete=W.read(complete_path)
        artifacts=W.inventory(directory,exclude=('COMPLETE.json','STOP.json'))
        W.require(W.sha(complete_path)==complete_hash and W.encoded(artifacts)==W.encoded(complete['artifacts']),
                  'Completed artifacts changed during inspection.')
        self._verified[name]={'complete_sha256':complete_hash,'config_sha256':W.sha(directory/'resolved-config.json'),
                             'artifacts':artifacts,'receipt':copy.deepcopy(receipt)}
        return receipt
