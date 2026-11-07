Git notes:
Update fork, add stuff to functionality_base:
git checkout functionality_base
git remote add upstream https://github.com/gramps-project/gramps.git (use git remote -v to verify)
git fetch upstream
git rebase upstream/master (this was wrong)
git rebase -i upstream/maintenance/gramps61 (interactive is quit weird)
(resolve any conflicts)
git push origin attributefix --force-with-lease

To add attributefix changes to functionality_base:
git checkout functionality_base
git merge attributefix
git push origin functionality_base