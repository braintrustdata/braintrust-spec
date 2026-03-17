# Braintrust Features

This folder contains descriptions of Braintrust features; its purpose is to help developers and agents quickly and accurately implement them.

## Adding a new feature

1. Create a new sub-folder with the feature name (e.g. `remote-evals`)
2. Add any markdown, diagrams, JSON/YAML, schema or other files as needed.

### Recommended descriptions

Add these if applicable:

#### **`README.md`**

A general overview of the feature from a product and customer perspective.

A good overview: 

- Concisely explains the purpose of the feature, illustrates its use, and describes the high-level of "how it works."
- Provides developers with a solid understanding of the customer asks/expectations so that developers may facilitate good user experience.
- Provides useful references, uses visuals (where appropriate), and is light on technical detail. 

*Rule of thumb: It should read like our public documentation.*

#### **`design.md`**

This provides a more comprehensive (but still relatively high-level) explanation of how the feature/system works end to end.

It covers in breadth:

1. Design goals and fundamental requirements (e.g. compatibility, throughput, etc.)
2. End-to-end feature flow across the system or lifecycle.
3. The role of the system components involved in the feature such as the API, databases, SDKs, etc.
4. The architectural patterns and their high-level use of subcomponents to drive the feature (e.g. data structures, interfaces, etc)
5. Any significant functional dimensions such as security, telemetry, error recovery, etc that warrant .

It may also include annotations for important caveats or risks that might encumber implementation or UX.

However it should NOT:

- Go into technical specifics such as parameters, formats, or other contracts beyond what is necessary to illustrate "the big picture." These details should be reserved for `contracts.md`.
- Prescribe implementation of sub-components, especially where it may reasonably vary between the different language SDKs for the purposes of performant and idiomatic implementation.

After reading this, a developer should have a comprehensive understanding of how the feature/system works as a whole. 

- **`contracts.md`**

This is a reference for the concrete technical communication between components in the proposed design. .

It should contain distinct subsections for each of the different kinds of "contracts" that components rely upon to communicate with one another, including but not limited to:

1. Data structures: e.g. structs, classes, serialized JSON/YAML/other, database records, etc
2. Interprocess APIs: e.g. HTTP, message queue protocols, etc
3. Intraprocess APIs: e.g. modules, service objects, public interfaces in SDKs, etc
4. Configuration: e.g. env vars, `.yml`/`.json`/`.conf` or other flat files, flags, global variables, etc

Each of these should provide a statement of clear purpose, rich technical detail about the inputs/outputs/formats, examples that illustrate common use and failure states, and any appropriate hyperlinks to other reference material or relevant code.

A good reference will enable a developer to provide accurate, compatible, resilient implementation that fits in well with the other system components. It would minimize the number of bugs, inconsistencies and trial-and-error in the course of implementing a feature. It also provides a great place for a developer to go to understand all the details of a specific API endpoint.

- **`validation.md`**

This describes how we should expect the feature to behave in order for us to consider it "complete".

It should describe a list of common scenarios and important edge cases, each detailed in its own subsection which includes:

1. Purpose: what we're trying to assert or prevent.
2. Conditions: anything notable about the environment (e.g. configuration, faults such as network failure, etc)
3. Inputs: what was being done. (e.g. inputs, format, etc)
4. Expectations: what we should observe (e.g. outputs, format, etc)

These should be readily convertible to actual test implementation in the relevant CI systems. If done well, it clarifies any important behavioral expectations for the developer, helps them address edge cases they may have missed, and generally improve the robustness of the implementation. Product engineers and developers should be to add new scenarios they encounter easily without needing to provide deep technical descriptions.

It should NOT:

- Be too technically specific to a particular language when it concerns SDKs (a.k.a. describe a specific fault in Ruby only)
- Be concerned with the specifics of the underlying design/behavior: it should be focused primarily on UX outcomes, less so the means that provide those.

- **`implementation.md`**

(TBD)