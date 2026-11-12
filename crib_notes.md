Git notes:
Update fork, add stuff to functionality_base:
git checkout master
git remote add upstream https://github.com/gramps-project/gramps.git (use git remote -v to verify)
git fetch upstream
git rebase upstream/master (this was wrong)
git rebase -i upstream/maintenance/gramps61 (interactive is quit weird)
(resolve any conflicts)
git push origin attributefix --force-with-lease

To fix line-ending issues:
git pull origin functionality_base
git config --global core.autocrlf true
git stash
git rm --cached -r .
git reset --hard HEAD
git fetch origin
git merge origin/attributefix
git push origin functionality_base

To add <feature-branch-name> changes to functionality_base:
git checkout functionality_base
git merge <feature-branch-name>
git push origin functionality_base

To change the starting point of the <feature-branch-name> branch to be functionality_base:
git fetch origin
git checkout <feature-branch-name>
git rebase functionality_base
git push origin <feature-branch-name> --force-with-lease

To squash all of the commits for a feature:
git reset --soft main
git commit -m "Implement complete feature X"
git push --force-with-lease

To update functionality_base changes to a branch that is based on it:
git fetch origin
git checkout <feature-branch-name>
git rev-list --count origin/functionality_base..HEAD (returns max number of conflict-resolution stops)
comm -12 <(git diff --name-only origin/functionality_base...HEAD | sort) <(git diff --name-only HEAD...origin/functionality_base | sort) # list files modified in both branches
git merge-tree --write-tree origin/functionality_base HEAD  #Test for overall conflicts
git rebase origin/functionality_base (git rebase --abort) to give up
git push --force-with-lease origin <feature-branch-name>

List all files touched/added by this feature branch:
git diff --name-only origin/functionality_base...origin/HEAD > changed_files.txt

Count the number of commits in a particular feature branch:
git rev-list --count functionality_base..origin/HEAD

To show what the branch which your branch is based off of:
git log --oneline --graph --decorate --simplify-by-decoration

Rename a branch:
git branch -m <new-name>
git push -u origin <new-name>
git push origin --delete <old-name>

Auto-accept "ours"
git fetch origin
git rebase -X ours origin/functionality_base

Remove a file that is in the parent branch (functionality_base):
git checkout origin/functionality_base -- <path/to/file>

To disable the "paging" in git:
git config --global core.pager cat

git config user.name "Kevin White"
git config user.email "gocaveman@gmail.com"

I see merge conflicts and I can't tell if I should accept ours or theirs.  Can you help me understand which one has newer features?

git rebase -X theirs origin/functionality_base