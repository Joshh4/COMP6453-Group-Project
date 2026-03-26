# COMP6453-Group-Project
Implementing Data Availability Sampling using the CONDA Scheme.

## Every Time You Start Working
```bash
source venv/bin/activate # or source venv/Scripts/activate for windows user
```
You must ensure you are in python 3.10 to support installed libraries.

## Git & Branching Standards

To maintain a clean history and enable automated deployments, we follow a strict branching and commit convention.

### 1. Branch Naming Convention

All branches must follow the structure: `type/directory-name/description`
- only exception to this aare the docs or chore branches

| Type | Description | Example |
| --- | --- | --- |
| `feat/` | A new feature for a specific aspect | `feat/commitment/committee` |
| `fix/` | A bug fix | `fix/utils/incorrect-calculations` |
| `refactor/` | Code changes that neither fix a bug nor add a feature | `refactor/sampling/sampler-schema` |
| `chore/` | Updates to build scripts, tools, or libraries | `chore/common/update-precommit` |
| `docs/` | Documentation changes only | `docs/` |

---

### 2. Pull Requests
**Open a Pull Request (PR):**
   - Ensure at least **one team member** reviews and approves
   - Evidence of comments/discussion must be visible in the PR before merging

### 3. Commit Message Standards

Commit messages should be detailed and specific. Avoid generic messages like "fixed bug" or "updates."

## Local Setup (One-Time)

To ensure your environment matches the team standards, run:
> **Windows users:** replace `source venv/bin/activate` with `source venv/Scripts/activate`
```bash

# 1. Clone the new repo
  git clone git@github.com:yuvran7700/ECHO_CLEARPATH.git
  cd ECHO_CLEARPATH

# 2. Create and Activate Virtual Environment (ROOT LEVEL)
  python -m venv venv
  source venv/bin/activate

# 3. install dependencies
  pip install -r requirements.txt

# 4. Set Up Pre-Commit Hooks
  pip install pre-commit
  sh util/setup.sh
```
After this, every `git commit` will automatically:
- Format your code with black
- Sort imports with isort
- Lint with flake8
- Reject commits over 200 lines