"""Sample jobs and skill knowledge for the demo. Replace with a real source later."""

JOBS = [
    {"jobId": "job_001", "title": "Data Analyst", "company": "ExampleCo", "location": "Indore",
     "deadline": "2026-11-30", "url": "https://example.com/jobs/001",
     "skills": ["python", "sql", "excel", "statistics"]},
    {"jobId": "job_002", "title": "Backend Developer Intern", "company": "Lumen Labs", "location": "Remote",
     "deadline": "2026-12-05", "url": "https://example.com/jobs/002",
     "skills": ["python", "fastapi", "postgresql", "git"]},
    {"jobId": "job_003", "title": "Frontend Developer", "company": "Pixelwork", "location": "Bhopal",
     "deadline": "2026-12-10", "url": "https://example.com/jobs/003",
     "skills": ["javascript", "react", "typescript", "css"]},
    {"jobId": "job_004", "title": "Machine Learning Engineer", "company": "Northwind AI", "location": "Indore",
     "deadline": "2026-12-15", "url": "https://example.com/jobs/004",
     "skills": ["python", "pytorch", "statistics", "sql"]},
    {"jobId": "job_005", "title": "Business Analyst", "company": "Ledgerly", "location": "Pune",
     "deadline": "2026-12-01", "url": "https://example.com/jobs/005",
     "skills": ["sql", "excel", "communication", "tableau"]},
]

# Known skills the resume parser looks for (lowercase).
KNOWN_SKILLS = sorted({s for j in JOBS for s in j["skills"]} | {"java", "c++", "docker", "aws", "figma"})

# Learning step per skill, used by the roadmap.
LEARNING = {
    # (milestone title, [free resource links], eta weeks). Links verified reachable on 2026-11-08.
    "sql": ("SQL fundamentals", ["ThoughtSpot SQL tutorial (formerly Mode) - https://mode.com/sql-tutorial/", "SQLBolt - https://sqlbolt.com/"], 2),
    "python": ("Python basics to projects", ["Official Python tutorial - https://docs.python.org/3/tutorial/"], 3),
    "excel": ("Excel for analysis", ["Microsoft Excel help & learning - https://support.microsoft.com/en-us/excel"], 1),
    "statistics": ("Statistics essentials", ["Khan Academy statistics - https://www.khanacademy.org/math/statistics-probability"], 3),
    "fastapi": ("Build an API with FastAPI", ["FastAPI tutorial - https://fastapi.tiangolo.com/tutorial/"], 2),
    "postgresql": ("PostgreSQL basics", ["Official PostgreSQL tutorial - https://www.postgresql.org/docs/current/tutorial.html"], 2),
    "git": ("Git and pull requests", ["Pro Git book, ch. 1-3 - https://git-scm.com/book/en/v2"], 1),
    "javascript": ("JavaScript fundamentals", ["javascript.info - https://javascript.info/"], 3),
    "react": ("React core concepts", ["react.dev learn - https://react.dev/learn"], 3),
    "typescript": ("TypeScript for JS developers", ["TypeScript handbook - https://www.typescriptlang.org/docs/handbook/intro.html"], 2),
    "css": ("CSS layout", ["web.dev Learn CSS - https://web.dev/learn/css"], 2),
    "pytorch": ("PyTorch basics", ["PyTorch tutorials - https://pytorch.org/tutorials/"], 4),
    "communication": ("Clear written communication", ["Practice: write a one-page project summary and ask a senior to critique it"], 1),
    "tableau": ("Tableau dashboards", ["Tableau getting-started guide - https://help.tableau.com/current/pro/desktop/en-us/gettingstarted_overview.htm"], 2),
    "java": ("Java fundamentals", ["Oracle Java tutorials - https://docs.oracle.com/javase/tutorial/"], 3),
    "c++": ("C++ fundamentals", ["learncpp.com - https://www.learncpp.com/"], 3),
    "docker": ("Docker basics", ["Docker Get Started - https://docs.docker.com/get-started/"], 1),
    "aws": ("AWS cloud basics", ["AWS Get Started - https://aws.amazon.com/getting-started/"], 2),
    "figma": ("Figma basics", ["Figma Learn Design - https://www.figma.com/resources/learn-design/"], 1),
}

INTERVIEW_QUESTIONS = {
    "Human Resources": [
        "A hiring manager says a vacancy must be filled urgently but keeps rejecting suitable candidates. How would you clarify the requirements and move the hiring process forward?",
        "Tell me about a time you handled a disagreement between two people. What did you do, and how did it end?",
        "An employee tells you something sensitive about their manager and asks you not to share it. How would you respond?",
        "How would you handle an employee who is consistently late but says the schedule is affecting their health or caregiving responsibilities?",
        "A new hire says their onboarding has been confusing and they do not know what is expected of them. What would you do?",
        "A manager wants you to dismiss an employee immediately, but the documented performance process has not been followed. How would you handle that request?",
        "How would you investigate a complaint of unfair treatment while protecting confidentiality and giving everyone a fair chance to respond?",
        "What would you look at to understand why employees are leaving a team, and how would you turn that information into action?",
        "Describe how you would plan an interview process for a role when several departments disagree about the ideal candidate.",
        "An employee is upset about a policy change and says HR is not listening. How would you handle the conversation?",
        "How would you make sure a recruitment process is fair, consistent and accessible to different candidates?",
        "Tell me about a time you had to communicate an unpopular decision or policy. How did you approach it?"
    ],
    "HR": [
        "A hiring manager says a vacancy must be filled urgently but keeps rejecting suitable candidates. How would you clarify the requirements and move the hiring process forward?",
        "Tell me about a time you handled a disagreement between two people. What did you do, and how did it end?",
        "An employee tells you something sensitive about their manager and asks you not to share it. How would you respond?",
        "How would you handle an employee who is consistently late but says the schedule is affecting their health or caregiving responsibilities?",
        "A new hire says their onboarding has been confusing and they do not know what is expected of them. What would you do?",
        "A manager wants you to dismiss an employee immediately, but the documented performance process has not been followed. How would you handle that request?",
        "How would you investigate a complaint of unfair treatment while protecting confidentiality and giving everyone a fair chance to respond?",
        "What would you look at to understand why employees are leaving a team, and how would you turn that information into action?",
        "Describe how you would plan an interview process for a role when several departments disagree about the ideal candidate.",
        "An employee is upset about a policy change and says HR is not listening. How would you handle the conversation?",
        "How would you make sure a recruitment process is fair, consistent and accessible to different candidates?",
        "Tell me about a time you had to communicate an unpopular decision or policy. How did you approach it?"
    ],
    "Human Relations": [
        "A hiring manager says a vacancy must be filled urgently but keeps rejecting suitable candidates. How would you clarify the requirements and move the hiring process forward?",
        "Tell me about a time you handled a disagreement between two people. What did you do, and how did it end?",
        "An employee tells you something sensitive about their manager and asks you not to share it. How would you respond?",
        "How would you handle an employee who is consistently late but says the schedule is affecting their health or caregiving responsibilities?",
        "A new hire says their onboarding has been confusing and they do not know what is expected of them. What would you do?",
        "A manager wants you to dismiss an employee immediately, but the documented performance process has not been followed. How would you handle that request?",
        "How would you investigate a complaint of unfair treatment while protecting confidentiality and giving everyone a fair chance to respond?",
        "What would you look at to understand why employees are leaving a team, and how would you turn that information into action?",
        "Describe how you would plan an interview process for a role when several departments disagree about the ideal candidate.",
        "An employee is upset about a policy change and says HR is not listening. How would you handle the conversation?",
        "How would you make sure a recruitment process is fair, consistent and accessible to different candidates?",
        "Tell me about a time you had to communicate an unpopular decision or policy. How did you approach it?"
    ],
    "Data Analyst": [
        "Walk me through a SQL query you wrote to answer a business question.",
        "How would you check a dataset for bad data before analysing it?",
        "Explain the difference between mean and median and when each misleads.",
        "A stakeholder asks for a dashboard but cannot explain what decision it should support. How would you clarify the requirement?",
        "You discover two reports show different numbers for the same metric. How would you investigate the discrepancy?",
        "Tell me about a time your analysis changed or challenged someone's assumption.",
        "How would you explain an uncertain finding to a non-technical stakeholder?",
        "A dataset has many missing values in an important column. How would you decide what to do?",
        "How would you test whether a change in a metric is meaningful or just normal variation?",
        "Describe how you would prioritise several analysis requests with the same deadline.",
        "What checks would you build to make a recurring report more reliable?",
        "Tell me about an analysis you would approach differently if you did it again."
    ],
    "Applied Scientist": [
        "You are given a dataset with millions of examples and noisy labels. How would you assess data quality before training a model?",
        "How would you choose an evaluation metric for an imbalanced classification problem, and what trade-offs would you consider?",
        "A model performs well on the training set but poorly on unseen data. How would you investigate and address the gap?",
        "How would you design an experiment to compare a simple baseline with a more complex machine-learning model?",
        "A research result looks promising, but the improvement is small and varies across random seeds. How would you determine whether it is reliable?",
        "How would you detect data leakage in a machine-learning pipeline?",
        "Describe how you would handle missing values, outliers and noisy labels in a real-world dataset.",
        "How would you decide whether a problem needs a machine-learning model or a simpler statistical or rule-based approach?",
        "A model has high overall accuracy but performs poorly for one important subgroup. How would you investigate this?",
        "How would you explain a model's limitations and uncertainty to a stakeholder who wants a definitive prediction?",
        "Tell me about a machine-learning or research problem you worked on. What hypothesis did you test, and how did you evaluate the result?",
        "If you had one week to improve an existing model, how would you identify the highest-value experiment to run?"
    ],
    "default": [
        "What interests you about this role, and which part of the work do you think will challenge you most?",
        "Tell me about a time you had to learn something unfamiliar to complete a task.",
        "Describe a disagreement you had with a teammate and how you worked through it.",
        "Tell me about a time you received difficult feedback. What did you do with it?",
        "Describe a task with an unclear goal. How did you decide what to do first?",
        "Tell me about a time something did not go to plan. How did you respond?",
        "How do you decide what to prioritise when several tasks are urgent?",
        "Give an example of how you explained a complex idea to someone with a different background.",
        "What is a piece of work you are proud of, and what specifically made it successful?",
        "Tell me about a decision you made with incomplete information.",
        "Describe a situation where you had to take responsibility for a mistake.",
        "What would you want to learn in your first three months in this role?"
    ]
}
