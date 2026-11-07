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