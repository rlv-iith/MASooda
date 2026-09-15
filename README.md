# Urban Aerial Hierarchical Swarm Governance

Simulation and evaluation of a hierarchical traffic-management system for autonomous drones operating in crowded urban airspace.

## Project Overview

The system combines local drone-to-drone decision-making with a centralized Drone Traffic Controller (DTC). Drones exchange information to make immediate safety decisions, while the DTC manages corridor allocation, traffic priorities, and global flow.

The simulation focuses on:

- Safe separation, collision avoidance, and destination arrival
- Heterogeneous drones with different priorities, speeds, routes, and communication capabilities
- Drone-to-drone, drone-to-DTC, and DTC-to-drone communication
- Low, medium, and high traffic densities, including merging and conflicting flows
- Communication loss, faulty data, false intent, and rule violations
- Resilient behavior when the DTC is unavailable or agents provide misleading information

## Scope

The core implementation uses a bounded 2.5D urban airspace with predefined corridors, intersections, entry and exit points, and obstacles. Drones are modeled primarily by position, velocity, destination, and priority. Detailed aircraft physics, full-city modeling, complex cyberattacks, and real-world certification are outside the core scope.

 The following sequence is the implementation plan for the project.
## Timeline
- 15th September 2026 - Project proposal was submitted to the Instructor


## Individual Contributions

### Abdur Rehman and Dhadheechi

- Build the live simulation world, including agent dynamics, the communication graph, rendering, and module integration
- Formalize safety requirements as Signal Temporal Logic (STL) specifications
- Implement STL robustness monitoring
- Assemble the final dashboard and visualization

### Lalith Vishnu

- Design and implement the distributed optimization layer using Alternating Direction Method of Multipliers (ADMM)
- Resolve yielding, merging, and rerouting conflicts between agents

### Bhuvan

- Implement Boids-style local rules for alignment, cohesion, and separation
- Implement corridor and platoon merging logic
- Support autonomous formation behavior

### Tanmay

- Develop the centralized DTC node
- Implement corridor allocation and priority arbitration across drone types
- Apply global traffic rules and priority ordering

### Sampadram

- Implement fault and attack injection
- Implement W-MSR-style resilient consensus
- Maintain resilient swarm behavior in the presence of malicious or faulty agents

## Demonstration Plan

The final demonstration will use a dual-screen dashboard:

1. **Live simulation:** A top-down airspace view showing colored drone agents, corridor lanes, malicious-agent indicators, and DTC directives.
2. **Live dashboard:** STL robustness, emergency-priority compliance, and an ADMM convergence timer.

The demonstration will cover normal corridor formation, a malicious drone with a dropped DTC connection, and emergency-drone priority routing.

## Evaluation Criteria

- Minimum separation and collision avoidance
- Successful destination arrival
- Priority compliance for emergency drones
- ADMM conflict-resolution convergence
- STL robustness over time
- Behavior under communication loss and faulty or malicious information

## Repository Structure

The repository is organized around the simulation, coordination algorithms, resilience mechanisms, safety monitoring, and visualization. Keep modules independently testable and document configuration or scenario changes alongside the relevant code.

## Development Standards

- Keep commits focused and use descriptive commit messages.
- Use consistent formatting and meaningful names.
- Document public interfaces, assumptions, and scenario configuration.
- Add tests for coordination, safety, resilience, and communication-loss behavior.
- Make experiments reproducible by recording parameters, traffic density, random seeds, and observed metrics.
- Keep core simulation logic separate from rendering and dashboard code.
