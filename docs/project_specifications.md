# Course Project Specifications, Deliverables & Grading Rubrics

This document extracts all general course guidelines, deliverable rules, evaluation criteria, and project tiering standards from the course specifications and administration guidelines.

---

## 1. Project Overview & Grading Weightage

The term project accounts for **30% of the overall course grade**. Assessment is split across four deliverables:

* **Project Proposal Presentation (4%)**: 15-minute team presentation.
* **Final Project Presentation & Demo (8%)**: 20-minute team presentation and prototype demonstration.
* **Project Final Report (15%)**: 5 to 30 pages comprehensive architectural report.
* **Overall Peer Evaluation (3%)**: Individual contribution score.

---

## 2. Deliverables & Required Slide Structure

### A. Project Proposal Presentation (15 Minutes)
The proposal presentation must cover four core sections:
1. **Context Setting & Business Goals**: Context setting, target user/customer base, and **strictly a maximum of 3 business goals**.
2. **Use Cases & Key Functions**: Core business use cases, system boundaries, and user interactions.
3. **Solution Design with Cloud Resources**: Proposed 3-tier architecture diagram, layer decoupling (e.g., queueing/messaging), resource allocation, RTO/RPO targets, and monitoring/alert setups.
4. **Implementation Plan & Scope Boundaries**: Explicitly stating **which parts will be implemented for the live demo vs. which parts are documented for enterprise design only**.

### B. Source Code & Prototype Rules
* **Source Code Flexibility**: Teams have full freedom to write custom code or adapt public open-source repositories to showcase cloud orchestration.
* **Demonstration Focus**: The live prototype keeps functional code to basic requirements, focusing heavily on how cloud managed services, infrastructure-as-code (IaC), and messaging flows support the application.
* **Module Simplification Allowed**: Certain complex external dependencies (e.g., third-party payment gateways) do not require live code execution for the demo, provided they are fully architected in the design.

---

## 3. Core Evaluation Criteria

Project submissions are evaluated across seven core engineering and management dimensions:

1. **Feasibility**: Alignment of business and technical requirements within the stated context settings.
2. **Resource Allocation & Justification**: Technical justification for selected compute, storage, database, network, and security services.
3. **Resource Linkage & Message Flow**: Asynchronous event streams, queue triggers, cron schedulers, and inter-service communication.
4. **Overall Design & Implementation**: Quality of architectural tiering, separation of concerns, and prototype execution.
5. **Monitoring, Observability & Alerts**: CloudWatch metrics, log aggregation, distributed tracing, and automated SNS alarm triggers.
6. **Scalability, Reliability & Availability**: Multi-AZ fault tolerance, auto-scaling mechanisms, data durability, and disaster recovery SLAs (RTO/RPO).
7. **Cloud Management Approach & Governance**: Infrastructure as Code (Terraform), role distribution across team members, cost management, and regulatory compliance (e.g., PDPA/GDPR).

---

## 4. Project Tiering & Grading Scale

Projects are graded on a **5-Tier Evaluation System** based on operational competency and alignment with the AWS Well-Architected Framework:

| Tier Level | Score / Standard | Description |
| :--- | :--- | :--- |
| **Tier 1 (Exceptional)** | **10 / 10** | Exceptional work surpassing basic assessment. Fully optimized across all **5 AWS Well-Architected Pillars** (Security, Reliability, Performance Efficiency, Cost Optimization, Operational Excellence). |
| **Tier 2 (Above Standard)** | **8 / 9** | Solution is fully functional and well-architected across key pillars (Security, Reliability, Sustainability), with minor room for improvement in engineering or management. |
| **Tier 3 (Basic Standard)** | **6 / 7** | Solution is functional based on business requirements and use cases, showing baseline cloud engineering competency. |
| **Tier 4 (Borderline)** | **5 or below** | Solution barely meets basic standard; requires further work on effective cloud resource utilization. |
| **Tier 5 (Unsatisfactory)** | **< 5** | Solution is non-functional, lacks critical features, or fails to satisfy basic business requirements. |

---

## 5. Architectural & System Design Metrics Checklist

When building architectural documentation and reports, solutions must address both **Business** and **Technical** metrics:

* **Business Metrics**:
  * **SLAs & KPIs**: Service Level Agreements (uptime, latency targets) and Key Performance Indicators (incident restoration time, mean time to detect).
  * **Cost Considerations**: Total Cost of Ownership (TCO), CAPEX vs. OPEX, data ingress/egress, and scale-to-zero economics.
  * **Compliance & Regulations**: Statutory data protection (PDPA / GDPR), PCI DSS for payment cards, and audit log retention.
  * **Business Continuity**: Recovery Time Objective (**RTO**) and Recovery Point Objective (**RPO**).
* **Technical Metrics**:
  * **Compute & Memory**: Machine type selections, container auto-scaling, and execution triggers.
  * **Network Design**: VPC subnets, route tables, NACLs (subnet perimeter filtering), Security Groups (host stateful firewalls), and API Gateways.
  * **Data Lifecycle & Retention**: Storage tiering (hot cache, operational DB, cold archive/Object Lock), retention periods, and backup frequency.
  * **Resiliency & High Availability**: Multi-AZ failover, queue decoupling, Dead-Letter Queues (DLQ), and circuit breaking.