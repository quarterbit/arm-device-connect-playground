# arm-device-connect-playground

Playground to showcase what Arm Device Connect can do.

A personal sandbox that sits next to a fork of [`arm/device-connect`](https://github.com/arm/device-connect)
(my fork: [`quarterbit/device-connect`](https://github.com/quarterbit/device-connect)). Demos are built and
iterated here in the open; whatever proves valuable gets cleaned up and promoted into a pull request back to
`arm/device-connect`.

## Demos

- **[`sunhaus/`](sunhaus/)** — SUNHAUS, a smart-home energy demo. One house, twelve Device Connect devices, one
  home-energy agent, a full simulated day compressed into three minutes.
  - [`sunhaus/CONCEPT.md`](sunhaus/CONCEPT.md) — the full concept: device roster, lifecycles, 3-minute demo
    script, repo structure, milestones.
  - [`sunhaus/sunhaus-demo-storyboard.html`](sunhaus/sunhaus-demo-storyboard.html) — the animated storyboard /
    demo UI shell.

## Working notes

Design and AI working history for these demos lives in the attached Claude Project
(**"Arm Device Connect Demo"**), intentionally kept out of this public repo. The `.gitignore` also excludes
`ai-thinking/`, `notes/`, and `scratch/` in case anything is drafted locally.
