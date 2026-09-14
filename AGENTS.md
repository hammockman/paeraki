# Agent Guidelines & Testing Rules

## Display & GUI Testing
- **Always use Xvfb for testing**: Never use the default or active user display (`DISPLAY=:0`, etc.) for running GUI applications, browser tests, or UI test scripts.
- Always execute commands via `xvfb-run -a <command>` or within a dedicated virtual display (e.g. `DISPLAY=:99`) to prevent windows from popping up on or interfering with the user's physical screen.
