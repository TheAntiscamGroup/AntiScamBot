gitpull() {
  if git pull; then
    return 0
  else
    return 1
  fi
}

echo "Updating directory"
if gitpull; then
  echo "Deploy success"
else
  echo "Stashing changes!"
  git stash
  echo "Resyncing..."
  gitpull
  echo "Remember to handle the unstashing later"
fi