I need to pull and integrate upstream changes into my current branch. Follow these exact steps:
1. Run git status and git remote -v to verify my working tree is clean and confirm the upstream remote URL (if missing, ask me for it).
2. Create a local backup branch named backup-before-upstream from my current HEAD before making changes.
3. Run git fetch upstream.
4. Show me a summary of incoming commits and modified files between my current branch and upstream/master (or the default upstream branch).
5. Merge upstream/master into my current branch using --no-ff (or rebase if I specify).
6. If merge conflicts occur, list every conflicting file, explain what changed upstream versus locally, and ask for my approval before resolving complex logic conflicts.

ChatGPT:
Here is my current Git status and remote setup: https://github.com/gramps-project/gramps
I want to sync my fork with the upstream repository while preserving my local changes on my_branch_name. Give me the exact terminal commands to fetch upstream, safely merge or rebase, and verify the result. Explain whether merge or rebase is safer for my setup.