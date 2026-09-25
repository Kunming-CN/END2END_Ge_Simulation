# End-to-end germanium detector simulation

## Current release: precomputed results, not an online solver

Open `docs/index.html` to browse the publishable library. It contains 17 detector models, field images, drift movies, pulse comparisons and downloadable signal tables. GeGI includes a 20-event, 34-channel interactive strip display and a separate supplementary notebook study.

Browser movies are pre-rendered 3D views. Free rotation of the full existing scenes still uses desktop ParaView. Synthetic multi-site deposits are not Geant4 particle-transport events or a Compton reconstruction.

The full local entry remains `Additional_Simulations/Visualization_3D/Open_Library.cmd`.

## Publish from the development computer

Double-click `Publish.cmd`. It rebuilds the public site, asks for GitHub browser authorization when needed, commits the approved publication files, pushes to `Kunming-CN/END2END_Ge_Simulation`, and configures GitHub Pages from `main:/docs`. It never force-pushes or uploads the entire calculation directory.

The first public deployment still requires completing the computer's GitHub CLI authorization. A linked ChatGPT GitHub account is a separate connection.

## One project, three clear areas

- `Additional_Simulations/` and `2D_GeGI detector Simulation/`: existing scientific workspace, preserved locally.
- `docs/`: generated publication deliverable; this is the content sent to GitHub Pages.
- `tools/`: migration, testing and publishing scripts. `.local/` holds ignored backups and test evidence.

`docs/` is an intentional distribution copy: it strips private machine paths and excludes raw field caches, ParaView states, manufacturer manuals, photographs and presentation slides. Do not edit its generated HTML by hand; change the exporter or source and rebuild.

## Collaboration and scope

`PROGRESS.md` records milestones and tested evidence. Update it with each meaningful change, then commit and push. This first repository snapshot distributes the website and its maintenance tools, **not yet a standalone calculation package**. Heavy caches and the unfinished simulation integration remain local until their reproducible interface is ready.

Next: make the computation package portable; then connect Geant4/remage deposits to SSD charge response, readout, and reconstructed energy. Preserve deposited truth energy separately from reconstructed energy. See `AGENTS.md` for development boundaries.
