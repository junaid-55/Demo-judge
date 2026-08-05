# Chakri Koi Local Runner

This project lets a learner solve programming problems in their own editor while code runs safely inside Docker on their own computer.

## What Happens When You Submit

1. You write a solution in any editor.
2. The local Chakri Koi Runner receives the solution.
3. It asks the backend for a signed run permission, then fetches the problem rules and tests.
4. It runs your solution in an isolated Docker container.
5. It checks every test and reports what passed, failed, timed out, or could not compile.
6. When the run finishes, the backend stores one complete submission record and all its test results together.

There is no incomplete submission record if the runner is unavailable or the computer shuts down during a run.

## Project Folders

- backend_draft: backend service, database, problems, and tests.
- source: editable runner source code, build tools, solutions, and source tests.
- user_agent: generated runner binary and user-facing files.
- ui: static Netlify application that delegates browser submissions to the loopback runner.

## Development

Build the user binary with: ./source/build.sh

Run source tests with: python -m unittest discover -s source/tests -v

Run package tests with: python -m unittest discover -s user_agent/tests -v

See TECHNICAL_README.md for implementation details.

See DEMO_README.md for creating problems and testing your own solutions locally.

See ui/README.md for deploying and testing the browser UI through Netlify.
