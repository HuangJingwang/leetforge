# BrushUp VS Code Extension

Sidebar panel for BrushUp — LeetCode study tracker.

## Features

- **Stats panel**: total problems, R1 progress, user info, AI usage
- **Struggles panel**: recently struggled problems (≥2 attempts)
- **Commands**:
  - `BrushUp: Sync Now` — trigger sync from VS Code
  - `BrushUp: Open Web Dashboard` — open full web UI
  - `BrushUp: Refresh` — refresh sidebar data

## Install

```bash
cd vscode-extension
npm install
# Press F5 in VS Code to run in Extension Development Host
```

## Requirements

- BrushUp CLI installed (`leetcode` command available)
- Data directory: `~/.leetcode_auto/`
