# Contract Examples (DRAFT)

Status: draft. Sample request/response payloads for each endpoint in the proposed API contracts. Those contracts are a draft dependency, not on main yet: they live on branch `docs/api-contracts-draft` (https://github.com/sarthak0116/slate/compare/main...docs/api-contracts-draft). If the contract changes, update these examples in the same PR. Use these exact payloads as frontend mock data until the backend exists.

## Resume

`POST /v1/resume`

```json
{
  "resumeId": "res_a91f2c",
  "parsed": {
    "name": "Aarav Kumar",
    "skills": ["python", "sql", "excel"],
    "education": [{ "degree": "B.Tech CSE", "institute": "IIITM Gwalior", "year": 2027 }],
    "experience": [{ "title": "Data Intern", "org": "ExampleCo", "months": 3 }]
  }
}
```

## Job matches

`GET /v1/jobs?query=data%20analyst&location=indore`

```json
{
  "jobs": [
    {
      "jobId": "job_4d21",
      "title": "Data Analyst",
      "company": "ExampleCo",
      "location": "Indore",
      "matchScore": 0.82,
      "deadline": "2026-11-30",
      "url": "https://example.com/jobs/4d21"
    },
    {
      "jobId": "job_9b07",
      "title": "Junior Business Analyst",
      "company": "SampleCorp",
      "location": "Remote",
      "matchScore": 0.67,
      "deadline": "2026-12-05",
      "url": "https://example.com/jobs/9b07"
    }
  ]
}
```

## Tailoring

`POST /v1/tailor`

Request:

```json
{ "resumeId": "res_a91f2c", "jobId": "job_4d21" }
```

Response:

```json
{
  "draftId": "draft_e310",
  "tailoredResume": "Aarav Kumar\nData Analyst candidate with Python and SQL experience...",
  "coverNote": "Dear ExampleCo team, ...",
  "status": "draft"
}
```

## Approval gate

`POST /v1/approvals`

Request:

```json
{ "draftId": "draft_e310", "decision": "approve" }
```

Response:

```json
{ "draftId": "draft_e310", "status": "approved" }
```

Rejecting uses `"decision": "reject"` and returns `"status": "rejected"`.

## Roadmap

`POST /v1/roadmap`

Request:

```json
{ "resumeId": "res_a91f2c", "targetRole": "Data Analyst" }
```

Response:

```json
{
  "milestones": [
    {
      "title": "SQL joins and window functions",
      "why": "Listed in 4 of 5 matched job descriptions, missing from resume",
      "resources": ["https://example.com/sql-course"],
      "etaWeeks": 2
    },
    {
      "title": "Dashboard project",
      "why": "No portfolio evidence of visualization work",
      "resources": ["https://example.com/tableau-public"],
      "etaWeeks": 3
    }
  ]
}
```

## Mock interview

`POST /v1/interview/mock`

Request:

```json
{ "targetRole": "Data Analyst", "mode": "text" }
```

Response:

```json
{ "sessionId": "int_77c1" }
```

`GET /v1/interview/int_77c1/feedback`

```json
{
  "summary": "Good SQL fundamentals; explanations of tradeoffs need work.",
  "weakAreas": ["statistics basics", "communicating reasoning"],
  "transcriptRef": "int_77c1"
}
```

## Error example

Every endpoint returns errors in this shape, with a specific `code`:

```json
{ "error": { "code": "draft_not_approved", "message": "Draft draft_e310 needs approval before use." } }
```
