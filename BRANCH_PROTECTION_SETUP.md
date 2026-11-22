# GitHub Branch Protection Setup for `main` Branch

This document provides the exact steps to configure branch protection on the `main` branch with the required CI status checks.

## Required CI Jobs (from `.github/workflows/ci.yml`)

The following CI jobs must be selected as required status checks:

1. **lint** - Lint & Format (`ruff check` + `ruff format --check`)
2. **typecheck** - Type Check (mypy)
3. **test** - Unit Tests
4. **integration** - Integration Tests
5. **build** - Build Wheel

## Manual Setup Steps (Requires GitHub Admin Access)

Since branch protection rules require GitHub Pro for private repositories via API, these steps must be performed manually by a repository admin (sergio) through the GitHub web interface.

### Step 1: Navigate to Branch Protection Settings
1. Go to the repository on GitHub
2. Click **Settings** (top tab)
3. Click **Branches** in the left sidebar (under "Code and automation")
4. Click **Add branch protection rule** (or **Add rule** if none exist)

### Step 2: Configure the Rule
**Branch name pattern:** `main`

**Enable the following options:**

1. ✅ **Require a pull request before merging**
   - ✅ Require approvals (recommended: 1)
   - ✅ Dismiss stale PR approvals when new commits are pushed
   - ✅ Require review from Code Owners (if CODEOWNERS file exists)

2. ✅ **Require status checks to pass before merging**
   - ✅ Require branches to be up to date before merging
   - **Status checks that are required:** (search and select each)
     - `lint`
     - `typecheck`
     - `test`
     - `integration`
     - `build`

3. ✅ **Require conversation resolution before merging** (optional but recommended)

4. ✅ **Do not allow bypassing the above settings**
   - This applies to administrators as well

5. ✅ **Lock branch** (optional)
   - Prevents force pushes to main

6. ✅ **Do not allow force pushes** (optional but recommended)

### Step 3: Save
Click **Create** (or **Save changes** if editing existing rule)

## Verification

After setup, verify the configuration works:

1. **Test PR that fails CI cannot be merged:**
   - Create a PR with a deliberate lint/typecheck/test failure
   - Confirm the "Merge" button is disabled until CI passes
   - Confirm status checks show as required

2. **Test PR that passes CI can be merged:**
   - Create a PR that passes all CI checks
   - Confirm the "Merge" button becomes enabled
   - Merge successfully

## Automated Alternative (GitHub Pro Required)

If the organization has GitHub Pro, this can be automated via API:

```bash
# Using gh CLI (requires GitHub Pro for private repos)
gh api --method PUT /repos/{owner}/{repo}/branches/main/protection \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["lint", "typecheck", "test", "integration", "build"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
EOF
```

Or using repository rulesets (newer approach):

```bash
gh api --method POST /repos/{owner}/{repo}/rulesets \
  --input - <<'EOF'
{
  "name": "Main Branch Protection",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main"],
      "exclude": []
    }
  },
  "rules": [
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          {"context": "lint"},
          {"context": "typecheck"},
          {"context": "test"},
          {"context": "integration"},
          {"context": "build"}
        ]
      }
    },
    {
      "type": "pull_request",
      "parameters": {
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": true,
        "required_approving_review_count": 1
      }
    },
    {
      "type": "required_linear_history"
    },
    {
      "type": "non_fast_forward"
    }
  ],
  "bypass_actors": []
}
EOF
```

## Notes

- The `coverage-report` job is **not** included as a required check since it runs `if: always()` and is for reporting only
- The `integration` job depends on `lint` (via `needs: lint`), so it will only run after lint passes
- The `build` job depends on `lint`, `typecheck`, and `test` (via `needs: [lint, typecheck, test]`)
- All 5 jobs run independently in parallel (except for the `needs` dependencies)