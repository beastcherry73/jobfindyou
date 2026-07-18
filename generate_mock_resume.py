import os
from fpdf import FPDF

class ResumePDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 18)
        self.set_text_color(15, 23, 42)
        self.cell(0, 8, 'VENU BABU', 0, 1, 'C')
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(79, 195, 247)
        self.cell(0, 6, 'SENIOR DEVOPS & CLOUD INFRASTRUCTURE ENGINEER', 0, 1, 'C')
        self.set_font('Helvetica', '', 9)
        self.set_text_color(100, 116, 139)
        self.cell(0, 5, 'Charlotte, NC | (555) 019-2831 | venu.babu@devops-tech.com | linkedin.com/in/venubabu-devops', 0, 1, 'C')
        self.ln(4)
        self.set_draw_color(226, 232, 240)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def section_title(self, title):
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(15, 23, 42)
        self.cell(0, 6, title.upper(), 0, 1, 'L')
        self.set_draw_color(79, 195, 247)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def body_paragraph(self, text):
        self.set_font('Helvetica', '', 9.5)
        self.set_text_color(51, 65, 85)
        self.multi_cell(0, 4.5, text)
        self.ln(2)

def generate():
    pdf = ResumePDF()
    pdf.add_page()
    
    # Summary
    pdf.section_title('Professional Summary')
    pdf.body_paragraph('Senior DevOps & Cloud Infrastructure Specialist with 6+ years of hands-on expertise automating enterprise CI/CD pipelines, orchestrating production Kubernetes (EKS/GKE) clusters, designing Terraform Infrastructure-as-Code (IaC), and enforcing zero-trust IAM security compliance across AWS & multi-cloud environments. Proven track record reducing deployment downtime by 45% and optimizing cloud expenditure by 30%.')
    
    # Technical Skills
    pdf.section_title('Core Technical Competencies')
    pdf.body_paragraph('Cloud Platforms: AWS (EC2, EKS, S3, RDS, CloudFront, IAM, VPC), GCP, Azure\nDevOps & CI/CD: Terraform, Ansible, Docker, Kubernetes, Helm, GitHub Actions, Jenkins, GitLab CI\nMonitoring & Observability: Prometheus, Grafana, Datadog, ELK Stack, AWS CloudWatch\nScripting & Automation: Python, Bash/Shell, Go, Groovy, YAML, JSON')
    
    # Professional Experience
    pdf.section_title('Professional Experience')
    
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 5, 'Senior DevOps Engineer | CloudScale Technologies (Charlotte, NC)', 0, 1, 'L')
    pdf.set_font('Helvetica', 'I', 8.5)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 4, 'Jan 2022 - Present', 0, 1, 'L')
    pdf.body_paragraph('- Architected and deployed production-grade Kubernetes (EKS) infrastructure serving 2.5M+ daily active users using Terraform IaC.\n- Automated blue/green deployment pipelines using Helm & GitHub Actions, reducing software deployment lead time from 4 hours to 12 minutes.\n- Enforced AWS IAM Least-Privilege policies and automated SOC2 security compliance scanning, achieving 100% audit compliance.')
    
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 5, 'DevOps & Systems Engineer | Enterprise Solutions Inc (Raleigh, NC)', 0, 1, 'L')
    pdf.set_font('Helvetica', 'I', 8.5)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 4, 'Jun 2018 - Dec 2021', 0, 1, 'L')
    pdf.body_paragraph('- Migrated 40+ legacy microservices from monolithic virtual machines to Docker containers, cutting server infrastructure costs by $120,000/year.\n- Configured Prometheus & Grafana real-time observability dashboards with automated PagerDuty alerting thresholds.\n- Maintained 99.99% uptime for core financial application services across multi-region AWS availability zones.')
    
    # Education & Certifications
    pdf.section_title('Education & Certifications')
    pdf.body_paragraph('Bachelor of Science in Computer Science & Information Technology\nCertifications: AWS Certified Solutions Architect - Professional | Certified Kubernetes Administrator (CKA)')
    
    pdf_path = os.path.join(os.getcwd(), 'Venu_Babu_Senior_DevOps_Engineer_Resume.pdf')
    pdf.output(pdf_path)
    print(f"Successfully generated PDF: {pdf_path}")

    txt_path = os.path.join(os.getcwd(), 'Venu_Babu_Senior_DevOps_Engineer_Resume.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('''VENU BABU
Senior DevOps & Cloud Infrastructure Engineer
Charlotte, NC | (555) 019-2831 | venu.babu@devops-tech.com | linkedin.com/in/venubabu-devops

PROFESSIONAL SUMMARY
Senior DevOps & Cloud Infrastructure Specialist with 6+ years of hands-on expertise automating enterprise CI/CD pipelines, orchestrating production Kubernetes (EKS/GKE) clusters, designing Terraform Infrastructure-as-Code (IaC), and enforcing zero-trust IAM security compliance across AWS & multi-cloud environments. Proven track record reducing deployment downtime by 45% and optimizing cloud expenditure by 30%.

CORE TECHNICAL COMPETENCIES
- Cloud Platforms: AWS (EC2, EKS, S3, RDS, CloudFront, IAM, VPC), GCP, Azure
- DevOps & CI/CD: Terraform, Ansible, Docker, Kubernetes, Helm, GitHub Actions, Jenkins, GitLab CI
- Monitoring & Observability: Prometheus, Grafana, Datadog, ELK Stack, AWS CloudWatch
- Scripting & Automation: Python, Bash/Shell, Go, Groovy, YAML, JSON

PROFESSIONAL EXPERIENCE
Senior DevOps Engineer | CloudScale Technologies (Charlotte, NC) [Jan 2022 - Present]
- Architected and deployed production-grade Kubernetes (EKS) infrastructure serving 2.5M+ daily active users using Terraform IaC.
- Automated blue/green deployment pipelines using Helm & GitHub Actions, reducing software deployment lead time from 4 hours to 12 minutes.
- Enforced AWS IAM Least-Privilege policies and automated SOC2 security compliance scanning, achieving 100% audit compliance.

DevOps & Systems Engineer | Enterprise Solutions Inc (Raleigh, NC) [Jun 2018 - Dec 2021]
- Migrated 40+ legacy microservices from monolithic virtual machines to Docker containers, cutting server infrastructure costs by $120,000/year.
- Configured Prometheus & Grafana real-time observability dashboards with automated PagerDuty alerting thresholds.
- Maintained 99.99% uptime for core financial application services across multi-region AWS availability zones.

EDUCATION & CERTIFICATIONS
- Bachelor of Science in Computer Science & Information Technology
- Certifications: AWS Certified Solutions Architect - Professional | Certified Kubernetes Administrator (CKA)
''')
    print(f"Successfully generated TXT: {txt_path}")

if __name__ == '__main__':
    generate()
