import os

RESUMES = [
    # ===== 1. POOR - Fresh grad, generic, no metrics =====
    {
        "filename": "mock_resume_01_poor.txt",
        "content": """Alexandra Martinez
alex.martinez@gmail.com | (555) 111-2222 | linkedin.com/in/alexmartinez

Education
University of Texas at Austin — Bachelor of Science in Computer Science (2023)
GPA: 3.1

Technical Skills
Languages: Java, Python, HTML
Tools: Git, VS Code, Excel

Projects
Event Management System
• Helped develop an event management application
• Used Java and MySQL
• Worked with a team

Library Management System
• Created a library system for tracking books
• Used Python and some frameworks

Experience
Intern, TechCorp Solutions (Summer 2022)
• Assisted senior developers with testing
• Helped write documentation
• Attended team meetings

Campus Bookstore, Sales Associate (2021 - 2023)
• Helped customers find products
• Managed inventory

Achievements
• Dean's List (one semester)
• Member of Computer Science Club
• Completed Java Certification

Languages
English (Native), Spanish (Intermediate)
"""
    },

    # ===== 2. BELOW AVERAGE - Some experience, weak bullets =====
    {
        "filename": "mock_resume_02_below_average.txt",
        "content": """James Chen
james.chen@outlook.com | (555) 333-4444 | linkedin.com/in/jameschen
San Francisco, CA

Summary
Software Engineer with experience in web development. Worked on several projects.

Skills
• JavaScript, React, Node.js
• HTML, CSS
• MongoDB, SQL
• Git

Experience

Junior Software Developer | DataFlow Systems | San Francisco, CA
May 2022 - Present
• Worked on the frontend of the main product
• Fixed bugs reported by QA team
• Participated in sprint planning and code reviews
• Helped with deployment

Associate Software Engineer | WebCraft Agency | Oakland, CA
Jan 2021 - April 2022
• Built websites for clients using React
• Did testing and debugging
• Met with clients
• Updated website content

IT Support Intern | Bay Area Medical Center
June 2020 - Dec 2020
• Helped with computer issues
• Set up new computers
• Worked on tickets

Projects

Personal Portfolio
• Made a portfolio website

Todo List App
• Created a todo list with React

Education

University of California, Berkeley — Bachelor of Arts in Computer Science (2020)
Minor in Mathematics

Certifications
• AWS Certified Cloud Practitioner
"""
    },

    # ===== 3. AVERAGE - Decent mid-level with some metrics =====
    {
        "filename": "mock_resume_03_average.txt",
        "content": """Priya Sharma
priya.sharma@icloud.com | (555) 555-6666 | linkedin.com/in/priyasharma
Austin, TX | (512) 555-6666

PROFESSIONAL SUMMARY
Full Stack Engineer with 4+ years of experience building web applications using React, Python, and AWS. Passionate about clean code and user experience.

TECHNICAL SKILLS
Languages: JavaScript/TypeScript, Python, SQL, HTML/CSS
Frameworks: React, Node.js, Express, Flask, Django
Cloud & DevOps: AWS (EC2, S3, Lambda), Docker, GitHub Actions
Databases: PostgreSQL, MongoDB, Redis
Tools: Git, Jira, Datadog, Sentry

WORK EXPERIENCE

Full Stack Engineer | FinFlow | Austin, TX
March 2022 - Present
• Developed RESTful APIs using Node.js/Express handling 50k+ daily requests
• Built React dashboard components with real-time data visualization using D3.js
• Migrated legacy PHP monolith to microservices architecture
• Reduced API response times by 35% through query optimization and Redis caching
• Wrote unit and integration tests achieving 80% code coverage

Software Engineer | CloudPulse | Dallas, TX
June 2020 - Feb 2022
• Built internal tools using React and Django
• Created CI/CD pipelines using GitHub Actions for automated testing and deployment
• Participated in on-call rotation handling production incidents
• Mentored 2 new graduate engineers during onboarding

Junior Developer | RetailHub | Austin, TX
Jan 2019 - May 2020
• Developed new features for e-commerce platform using Python/Django
• Fixed average of 15 bugs per sprint
• Collaborated with design team on UI/UX improvements

EDUCATION

University of Michigan, Ann Arbor
Bachelor of Science in Computer Science (2018)
• GPA: 3.5
• Coursework: Data Structures, Algorithms, Operating Systems, Databases

PROJECTS

Real-time Chat Application
• Built WebSocket-based chat app with React frontend and Node.js backend
• Implemented message queuing with Redis Pub/Sub for horizontal scaling
• Deployed on AWS ECS with auto-scaling

Expense Tracker API
• Designed and built a personal finance tracking API with Django REST Framework
• Integrated Plaid API for automatic bank transaction syncing
</attachment>
"""
    },

    # ===== 4. GOOD - Strong senior IC with solid metrics =====
    {
        "filename": "mock_resume_04_good.txt",
        "content": """Michael Okafor
michael.okafor@gmail.com | (555) 777-8888
linkedin.com/in/michaelokafor | Seattle, WA | (206) 555-7777

PROFESSIONAL SUMMARY
Senior Software Engineer with 7+ years of experience architecting distributed systems and leading platform engineering initiatives. Specializing in scalable microservices, cloud-native architecture on AWS, and mentoring engineering teams. Reduced infrastructure costs by 40% and improved system reliability to 99.97% uptime across three major platform migrations.

CORE COMPETENCIES
• Distributed Systems & Microservices Architecture
• Cloud Infrastructure (AWS, GCP)
• Java, Kotlin, Python, Go
• Kubernetes, Docker, Terraform
• System Design & Performance Optimization
• Technical Leadership & Mentoring
• CI/CD & Developer Experience

PROFESSIONAL EXPERIENCE

Senior Software Engineer | Atlas Commerce | Seattle, WA
Jan 2021 - Present
• Architected event-driven microservices platform handling 10M+ daily transactions using Java 17, Spring Boot, and Apache Kafka, improving system throughput by 300%
• Designed and implemented multi-region active-active deployment on AWS EKS serving users across US, EU, and APAC with sub-100ms p99 latency
• Reduced cloud infrastructure costs by $1.2M annually through right-sizing, spot instance adoption, and implementing auto-scaling policies
• Led migration of 60+ services from monolithic architecture to event-driven microservices over 18 months with zero downtime
• Established engineering standards including code review processes, testing requirements (85% coverage minimum), and incident response playbooks
• Mentored 5 mid-level engineers through promotion cycles, with 3 achieving senior titles

Software Engineer II | NexaPay | San Francisco, CA
June 2018 - Dec 2020
• Built real-time payment processing pipeline handling $500M+ monthly transaction volume with exactly-once semantics using Kafka Streams and PostgreSQL
• Reduced payment settlement latency from 24 hours to 90 seconds by redesigning batch processing to streaming architecture
• Implemented distributed tracing across 25+ microservices using OpenTelemetry and Jaeger, reducing mean time to resolution by 60%
• Designed and implemented idempotent API patterns preventing duplicate payment processing, saving $2M+ in potential losses

Software Engineer | HealthBridge Technologies | San Francisco, CA
Sept 2016 - May 2018
• Developed HIPAA-compliant patient data platform serving 500+ hospitals nationwide
• Built scalable document storage system using AWS S3 and DynamoDB handling 2M+ medical records
• Implemented role-based access control (RBAC) system for 50k+ healthcare provider users
• Reduced database query latency by 70% through index optimization and query refactoring

EDUCATION

Carnegie Mellon University — Master of Science in Computer Science (2016)
• Research: Distributed Consensus Protocols
• GPA: 3.8

University of Washington — Bachelor of Science in Computer Engineering (2014)
• Magna Cum Laude | GPA: 3.7
• Dean's List all semesters

PUBLICATIONS & TALKS
• "Event-Driven Architecture at Scale" — AWS re:Invent 2023 Conference Speaker
• "Migrating Monoliths to Microservices: A Practical Guide" — IEEE Software Magazine, 2022
• "Distributed Tracing in Production Systems" — QCon San Francisco 2022

CERTIFICATIONS
• AWS Solutions Architect — Professional
• Certified Kubernetes Administrator (CKA)
• Google Cloud Professional Data Engineer
</attachment>
"""
    },

    # ===== 5. EXCELLENT - Staff/Principal level, exceptional =====
    {
        "filename": "mock_resume_05_excellent.txt",
        "content": """DR. SARAH VASQUEZ-OKAFOR
sarah.vasquez@alum.mit.edu | (650) 999-8888
linkedin.com/in/sarahvasquez | Palo Alto, CA

STAFF SOFTWARE ENGINEER | DISTRIBUTED SYSTEMS & AI INFRASTRUCTURE

Building the infrastructure that powers machine learning at planetary scale. 12+ years of experience designing distributed systems, leading 40+ engineer organizations, and shipping products used by billions.

EXECUTIVE SUMMARY

Staff Engineer with a PhD in distributed systems, combining deep technical expertise with organizational leadership. Led the architecture of ML training infrastructure that reduced model training time by 75% across 10k+ GPU clusters. Authored 8 peer-reviewed papers (2,400+ citations) and 6 patents in distributed computing and storage systems.

TECHNICAL EXPERTISE

Systems & Infrastructure: Distributed Systems, Apache Kafka, Apache Spark, Ray, Kubernetes, Envoy, Linkerd
Cloud & Platform: AWS, GCP, Azure, Terraform, Pulumi, Vault, Consul
Languages: Go, Rust, C++, Python, Java, Scala
ML/AI: PyTorch, TensorFlow, JAX, NVIDIA CUDA, TensorRT, MLFlow
Databases: FoundationDB, CockroachDB, Cassandra, Redis, PostgreSQL
Leadership: Technical Strategy, Org Design, Mentorship, Incident Command

PROFESSIONAL EXPERIENCE

Staff Software Engineer | Vertex AI | Google | Mountain View, CA
2021 - Present
• Architect and lead the distributed training orchestration layer for Vertex AI, serving 50k+ ML engineers training 200k+ models monthly across the global Google Cloud fleet
• Designed a novel gradient compression algorithm reducing inter-GPU communication by 85%, enabling efficient training of 1T+ parameter models across 10k+ GPU clusters
• Led the migration of training infrastructure from bare-metal to Kubernetes-based orchestration, improving cluster utilization from 45% to 82% and saving $40M+ annually in compute costs
• Established the ML Infrastructure Reliability team (SRE for AI), defining SLIs/SLOs/SLAs for model training pipelines achieving 99.95% training completion rate
• Authored internal design docs adopted as Google-wide standards for GPU cluster networking topology
• Mentored 12 engineers across 3 teams; 6 promoted to senior, 2 to staff

Senior Distributed Systems Engineer | Amazon Web Services | Seattle, WA
2017 - 2021
• Founding engineer of Amazon EKS Anywhere — designed the control plane architecture for hybrid Kubernetes deployments adopted by 3,000+ enterprise customers
• Built cluster-autoscaler algorithms supporting 50k+ node fleets with sub-30 second scale-up latency, enabling customers to handle 10x traffic spikes during Prime Day
• Designed and implemented cross-region data replication protocol achieving RPO < 5 seconds and RTO < 30 seconds for stateful workloads on Kubernetes
• Reduced AWS EBS CSI driver latency by 40% through block-level caching and concurrent volume attachment optimization
• Obtained 3 patents in container scheduling and cloud storage optimization
• Served as on-call escalation engineer for AWS Container Services, managing 20+ P0 incidents with 100% resolution within SLA

Distributed Systems Engineer | MongoDB, Inc. | New York, NY
2014 - 2017
• Contributed to distributed storage engine for MongoDB Atlas, managing 1PB+ customer data across multi-region clusters
• Designed and implemented automated index management system reducing DBA intervention by 95% for 10k+ customer clusters
• Built distributed backup/restore system supporting point-in-time recovery with 5-second granularity across 3 availability zones
• Performance optimization: improved WiredTiger storage engine throughput by 35% for write-heavy workloads

EDUCATION

Massachusetts Institute of Technology (MIT)
Ph.D. in Computer Science — Distributed Systems (2014)
• Dissertation: "Low-Latency Geo-Distributed Storage Protocols for Global-Scale Applications"
• Advisor: Dr. Barbara Liskov
• GPA: 4.9/5.0

Stanford University
M.S. in Computer Science — Systems & Networking (2010)
• GPA: 3.95/4.0

University of Illinois Urbana-Champaign
B.S. in Computer Engineering — Summa Cum Laude (2008)
• GPA: 3.98/4.0 | Bronze Tablet | Highest Departmental Honors

SELECTED PUBLICATIONS
• Vasquez-Okafor, S., et al. "Hermes: Efficient Gradient Compression for Training Large Language Models at Scale." OSDI 2024.
• Vasquez-Okafor, S., et al. "GlobalFS: A Strongly Consistent Geo-Replicated File System." SOSP 2023. (Best Paper Award)
• Vasquez-Okafor, S., et al. "Kairos: Low-Latency Metadata Operations in Distributed Storage." USENIX ATC 2022.
• Vasquez-Okafor, S. "Orchestrating Containerized Stateful Workloads at Scale." Communications of the ACM, 2021.

PATENTS
• US Patent 11,234,567: "System and Method for Cross-Region Data Replication in Container Orchestration Platforms"
• US Patent 11,098,765: "Cluster Auto-Scaling Using Predictive Workload Modeling"
• US Patent 10,987,654: "Distributed Index Management for Database Systems"
• US Patent 10,876,543: "Optimized Block-Level Caching for Cloud Storage Volumes"
• US Patent 10,765,432: "Gradient Compression for Distributed Machine Learning"
• US Patent 10,654,321: "Container Scheduling Optimization Using Network Topology Awareness"

LEADERSHIP & SERVICE
• Program Committee: OSDI, SOSP, USENIX ATC (2020-2024)
• Co-chair: ACM SIGOPS Workshop on Distributed Systems (2023)
• Google AI Infrastructure Technical Advisory Board Member
• Women in Systems Engineering (WiSE) — Founding Mentor, Bay Area Chapter
• Reviewer: IEEE Transactions on Parallel and Distributed Systems

LANGUAGES
English (Native), Spanish (Native), Mandarin Chinese (Professional Working)
</attachment>
"""
    }
]

def generate_all():
    output_dir = os.path.join(os.getcwd(), "mock_resumes")
    os.makedirs(output_dir, exist_ok=True)
    for r in RESUMES:
        path = os.path.join(output_dir, r["filename"])
        with open(path, "w", encoding="utf-8") as f:
            f.write(r["content"].strip())
        print(f"Generated: {path}")
    print(f"\nAll 5 mock resumes created in: {output_dir}")

if __name__ == "__main__":
    generate_all()
