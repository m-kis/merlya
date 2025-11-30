#!/bin/bash
# Script to create GitHub issues for mypy type errors
# Usage: ./create_mypy_issues.sh <mypy_output_file>

set -e

MYPY_OUTPUT="$1"

if [ -z "$MYPY_OUTPUT" ] || [ ! -f "$MYPY_OUTPUT" ]; then
    echo "Usage: $0 <mypy_output_file>"
    echo "Example: mypy athena_ai/ --ignore-missing-imports > mypy_errors.txt"
    echo "         $0 mypy_errors.txt"
    exit 1
fi

# Parse mypy output and create issues
while IFS= read -r line; do
    # Skip empty lines
    [[ -z "$line" ]] && continue

    # Extract file, line, and error message
    # Format: athena_ai/file.py:123: error: Message [error-code]
    if [[ $line =~ ^([^:]+):([0-9]+):\ error:\ (.+)\ \[(.+)\]$ ]]; then
        FILE="${BASH_REMATCH[1]}"
        LINE="${BASH_REMATCH[2]}"
        MESSAGE="${BASH_REMATCH[3]}"
        CODE="${BASH_REMATCH[4]}"

        # Create issue title
        TITLE="[mypy] ${CODE}: ${FILE}:${LINE}"

        # Create issue body
        BODY="## MyPy Type Error

**File:** \`${FILE}\`
**Line:** ${LINE}
**Error Code:** \`${CODE}\`

### Error Message
\`\`\`
${MESSAGE}
\`\`\`

### Context
\`\`\`python
# Line ${LINE} in ${FILE}
# Check the file for context
\`\`\`

### Action Required
- [ ] Fix the type error
- [ ] Add appropriate type hints
- [ ] Ensure mypy passes for this file

### Labels
- type: bug
- priority: medium
- area: type-safety"

        # Create the issue
        echo "Creating issue: $TITLE"
        gh issue create \
            --title "$TITLE" \
            --body "$BODY" \
            --label "type:bug,priority:medium,area:type-safety,mypy" \
            || echo "Failed to create issue for: $TITLE"

        # Rate limiting - wait 1 second between issues
        sleep 1
    fi
done < "$MYPY_OUTPUT"

echo "✅ Finished creating issues"
