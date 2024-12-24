lint: black
  uv run pylint --fail-under 9 $(git ls-files '*.py')

isort:
  uv run isort $(git ls-files '*.py')

black: isort
  uv run black $(git ls-files '*.py')


clean:
  rm -f dvr.sqlite
