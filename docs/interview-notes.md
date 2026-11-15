# Explaining this project honestly

## A 30-second introduction

“I built an independent integration lab to learn how a healthcare agent obtains reliable source data. It reads public synthetic FHIR records, stores a validated snapshot in SQL Server, and reconciles a reporting copy in Oracle. A LangGraph-backed agent calls two read-only tools on Vertex AI and produces a draft with evidence references. I check the evidence and require a human decision before the local patient preview shows a reply.”

## What is FHIR?

FHIR, pronounced “fire,” stands for Fast Healthcare Interoperability Resources. It defines common healthcare resources and ways to exchange them. In this lab, Patient identifies the test record, Encounter represents a visit, and ExplanationOfBenefit records insurance processing. A FHIR API does not automatically prove who is allowed to see a record; real identity and authorization need separate controls.

## Why both SQL Server and Oracle?

To practice two requested database technologies and demonstrate a verifiable handoff. SQL Server is the source store for imported records and review decisions. Oracle is a reporting copy. This is a learning design, not a claim that a particular hospital uses both databases for the same job.

## What did you implement yourself?

The source-specific patient mapping, reference checks, reduced record projection, parameterized database adapters, transactional reimports, cross-database payload verification, two agent tools, structured draft checks, local review state, and English UI. The input fixture comes from the open-source Synthea project and is attributed; the live endpoint is the public SMART test server.

## Where is the agent?

`app/agent.py` uses LangChain's `create_agent`, which runs on LangGraph. The real Vertex model chooses calls to the fixed-scope SQL Server and Oracle tools, receives their results, and returns a structured draft. The import and approval functions are ordinary application workflow logic. I am not claiming that every step is an autonomous agent.

## What if a record is incomplete?

The verified live patient had 23 encounters and no EOB. The agent reported that insurance-payment information was unavailable. An EOB is also different from a current patient bill, so even the fixture's recorded charges and payments do not justify inventing a final patient balance.

## How do you prevent the wrong patient's record from being used?

The import checks Encounter/EOB references against the selected test Patient. Storage keys include both source and patient ID. Agent tools receive no caller-controlled SQL or patient-ID argument; they are bound to the selected record. This lab's record selection is a local demonstration, not real patient login authorization or a production identity-matching solution.

## What did you test?

Fourteen automated checks, including real SQL Server and Oracle integration. I verified reimport idempotence, parameterized queries, altered-copy detection, reference and amount checks, and rejection of failed, stale, or already-reviewed drafts. Two live model runs and browser checks demonstrated that review decisions persist after a page reload.

## Does this demonstrate Epic, ServiceNow, UKG, or UiPath experience?

This lab demonstrates bounded hands-on FHIR, SQL Server, Oracle, and Vertex/agent integration. It does not connect to Epic, ServiceNow, or UKG. My separate Revenue Cycle Agent project integrates UiPath Maestro and Action Center. Neither side project should be represented as employment experience, a hospital deployment, or production vendor-platform expertise.

## Possible resume wording — independent project

“Built a FHIR R4 integration prototype using public synthetic records, SQL Server, and Oracle; added patient-reference validation, idempotent imports, payload reconciliation, and a Vertex AI/LangGraph agent with read-only tools and persisted human review.”

This wording describes verified project work. It should remain separate from employer achievements and claims about years of platform experience.
