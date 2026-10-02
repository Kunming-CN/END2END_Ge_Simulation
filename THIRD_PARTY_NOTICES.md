# Software, model and source rights

The project software license, when adopted by the owner, covers original project
software and original maintained-source documentation. It does not relicense third-party
software, scientific inputs, model snapshots or generated scientific datasets.
A public file and a provenance citation are not a grant of all reuse rights.

| Material | Authority and boundary |
|---|---|
| Original project runners, tools and maintained-source documentation | Project software license once selected; retain individual third-party notices. |
| `models/` and the identical website/model ZIP snapshots | Exact original configurations; source provenance and candidate/reference limitations are in `models/catalog.json`. Separate permission/terms must be checked for reuse or redistribution, including GeGI's private-source provenance and the shared ADL configuration. These bytes are not relicensed here. |
| `scenarios/assets/` and generated geometry representations | Derived input descriptions retain upstream provenance; project software licensing does not grant rights to underlying source material. |
| `docs/` numerical results, plots, geometry assets and archived presentations | Engineering result/provenance records, not a blanket software-license grant for scientific data or underlying third-party content. Keep exact artifact identities and limitations. |
| SSD, Geant4, remage, ParaView and environment dependencies | Separate upstream software and their own licenses; pinned versions/trees remain in the existing manifests and source records. A current upstream license is not evidence that every model is covered. |
| Original LBNL cryostat source files | `transport/cryostat-source.json` records that no explicit license was found in the pinned upstream tree. Originals remain locally fetched and hash checked; not redistributed or relicensed by this project. |
| `.local/` private inputs, manuals, images and permanent scientific evidence | Remain local; no new publication or license grant is implied. |

Do not add upstream code, models, photographs, manuals or experimental data to a
PR without recording their source and permission. Attribution alone cannot resolve
an unknown license. Resolve rights for the specific asset before distributing it;
do not change its model parameters or provenance to conceal the issue.

Cite this project's software using `CITATION.cff`, and cite the upstream tools and
physical/model sources actually used. A citation is not experimental certification.
