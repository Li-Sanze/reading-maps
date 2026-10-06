#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

git ls-files -z --cached | while IFS= read -r -d '' path; do
  lower_path=$(printf '%s' "$path" | LC_ALL=C tr '[:upper:]' '[:lower:]')
  case "$lower_path" in
    *.epub|*.pdf|*.mobi|*.azw3|*.djvu|*.txt|*.azw|*.kfx|*.docx|*.doc|*.rtf|*.fb2)
      printf 'Blocked original-book file: %s\n' "$path" >&2
      exit 1
      ;;
    books/*.md|books/*.markdown)
      printf 'Blocked book Markdown source: %s\n' "$path" >&2
      exit 1
      ;;
  esac
  case "/$lower_path/" in
    */sources/*)
      printf 'Blocked sources path: %s\n' "$path" >&2
      exit 1
      ;;
  esac
done
