Git notes:
Update fork, add stuff to functionality_base:
git checkout functionality_base
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

To add attributefix changes to functionality_base:
git checkout functionality_base
git merge attributefix
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
git rebase origin/functionality_base
git push --force-with-lease origin <feature-branch-name>

List all files touched/added by this feature branch:
git diff --name-only functionality_base...mediafix > changed_files.txt
