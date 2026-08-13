# HANDOFF — Arm Device Connect demo (SUNHAUS)

Running-start notes for continuing this work (e.g. in Claude Code, locally). Last updated 2026-08-13.

## Goal

Build **SUNHAUS**, a smart-home energy demo on top of [`arm/device-connect`](https://github.com/arm/device-connect),
iterate on it in this public playground, and promote the pieces worth keeping into a pull request back to Arm.

Full concept (device roster, lifecycles, 3-minute demo script, repo structure, milestones):
[`sunhaus/CONCEPT.md`](sunhaus/CONCEPT.md). Animated storyboard / demo UI shell:
[`sunhaus/sunhaus-demo-storyboard.html`](sunhaus/sunhaus-demo-storyboard.html).

## Repo layout & why

Two sibling repos live under `E:\repos\device-connect\`:

- **`arm-device-connect-playground/`** (this repo, public) — sandbox where demos are built in the open.
- **`device-connect/`** — clone of the fork [`quarterbit/device-connect`](https://github.com/quarterbit/device-connect),
  which was forked from [`arm/device-connect`](https://github.com/arm/device-connect). This is what PRs go through.
  *(Not cloned locally yet — see step 2 below.)*

Fork, not a direct clone of Arm's repo, because there's no push access to the `arm` org — the fork is the
writable copy that PRs originate from.

## The split (what goes where)

- **Demo work** → this playground, then promoted to the fork for a PR.
- **AI thinking / chat history** → the Claude Project **"Arm Device Connect Demo"**, deliberately kept out of
  the repo. `.gitignore` also excludes `ai-thinking/`, `notes/`, `scratch/`, and `files.zip`.
- Nothing AI-transcript-shaped should end up in the PR to Arm.

## Current state

- Playground has the SUNHAUS concept + storyboard organized under `sunhaus/`.
- `.gitignore` and `README.md` are in place.
- `files.zip` (the original download) is still present but gitignored — safe to delete.
- The fork has been created on GitHub but **not cloned locally yet**.

## Next steps

1. Commit the organized playground:
   ```bash
   cd E:\repos\device-connect\arm-device-connect-playground
   del files.zip                 # optional; gitignored anyway
   git add . && git commit -m "Add SUNHAUS demo concept + storyboard" && git push
   ```
2. Clone the fork as a neighbor and wire up the upstream remote:
   ```bash
   cd E:\repos\device-connect
   git clone git@github.com:quarterbit/device-connect.git
   cd device-connect
   git remote add upstream git@github.com:arm/device-connect.git && git fetch upstream
   ```
3. Start building against milestone **M0** in `sunhaus/CONCEPT.md` (skeleton: repo + CI + simclock +
   one discoverable device, `inverter-01`).
4. When a piece is clean and valuable, copy it into a feature branch in the fork, push, and open a PR
   `quarterbit/device-connect` → `arm/device-connect`:
   ```bash
   cd E:\repos\device-connect\device-connect
   git checkout -b example/sunhaus
   # copy the clean files over from the playground
   git add . && git commit -m "Add SUNHAUS example" && git push origin example/sunhaus
   ```
   Keep the fork current first with `git merge upstream/main` (or rebase) before opening the PR.
