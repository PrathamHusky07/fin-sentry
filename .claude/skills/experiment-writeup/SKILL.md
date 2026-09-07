---
name: experiment-writeup
description: "Follow this pattern when running any of the three experiments described in the spec (load test on Day 10, cost-versus-accuracy sweep on Day 10, reliability-under-failure on Day 9), the Cohen's kappa threshold sweep on Day 6, or any smaller ad-hoc experiment where a number goes into the README. Triggers on any work that produces a finding for the writeup, including capturing baseline numbers, generating result charts, or updating the experiments section of the README."
---

# Experiment writeup pattern

The story a senior interviewer respects is not about features. It is about findings. Every experiment on this project produces a finding. Every finding follows the same structure. Follow the pattern so all three experiments in the writeup read consistently and so an interviewer can compare them at a glance.

## The five parts of every finding

Every experiment writeup has five sections in this order.

**One. The question.** One sentence. What are we actually trying to learn. Not what we ran, but what we wanted to know. "Does the frontier tier still pay for itself past ten percent sampling on FinQA hallucination detection." Not "we ran the platform at different sampling rates."

**Two. The setup.** A short paragraph. What we ran, on what dataset, for how long, with what other variables held fixed. Enough that a reader could reproduce it. Include exact model versions, dataset versions, and the git commit hash of the platform. If a decision had to be made about a variable that could plausibly go either way, name the decision and the reason.

**Three. The numbers.** Actual measurements, not adjectives. Present as either a small table or a single clean chart. Every number has a unit. Every chart has axis labels and a caption. If uncertainty is meaningful, report it — a range, a confidence interval, or the standard deviation across runs. Do not report a single number as if it were exact when it was measured once.

**Four. The finding.** One or two sentences. What we learned. This is what the interviewer remembers. It should be specific enough to be wrong. "Below fifteen percent frontier sampling, AUROC on FinQA drops from 0.79 to 0.71" is a finding. "Frontier judging is important" is not. If the finding is a surprise, say so. If it confirmed the hypothesis, say so.

**Five. The consequence.** What we did about it. Did the platform's default configuration change based on this finding. Is a threshold now derived instead of guessed. Is a component now known to fail under a specific condition. If nothing changed, say so and explain why.

## The three experiments in the spec

Each of these produces a finding. Do not skip parts. Do not add parts.

### Load test (Day 10)

**Question.** How does the gateway perform at one thousand requests per minute with all rails enabled, and where does it start to break.

**Setup measurements to capture.** Gateway P50, P95, and P99 latency. Judge worker backlog over time. Dropped event count. CPU and memory usage of every container in the Docker Compose stack. Which rail is the latency bottleneck.

**Presentation.** One line chart of P99 latency over the load-test window. One bar chart of per-rail latency broken down by layer. One row of scalar numbers for backlog and dropped events.

**Consequence to look for.** The bottleneck rail is either optimized or its latency budget is officially raised. The judge worker pool size is either sufficient or expanded.

### Cost versus accuracy sweep (Day 10)

**Question.** At what frontier-tier sampling rate does additional frontier judging stop paying for itself on FinQA hallucination detection.

**Setup measurements to capture.** For each of three configurations (frontier only, ten percent frontier plus flash, flash only), the AUROC of the ensemble decision against the FinQA-hallucination-detection labels, the total tokens consumed by the frontier tier, and the wall-clock time. Do not extrapolate. Run each configuration until at least two hundred sampled decisions have been made.

**Presentation.** A single chart with sampling rate on the x-axis and AUROC on the y-axis. Points at zero, ten, and one hundred percent. Cost per thousand requests annotated at each point.

**Consequence to look for.** The default sampling rate in the platform configuration is set based on this experiment, not chosen ahead of time. If the spec says twenty percent is the literature-suggested crossover, the finding either confirms that or does not, and the platform's default reflects the finding.

### Reliability under failure (Day 9)

**Question.** How does the platform behave when three real failure modes occur, and does it fail closed correctly.

**Setup.** Three separately scripted scenarios. In scenario one, the Gemini API is made to return HTTP 500 for sixty seconds. In scenario two, one of the three frontier models is killed mid-run. In scenario three, the frontier worker pool is saturated by injecting a burst of ten thousand events into Redpanda.

**Measurements to capture.** For each scenario, whether the gateway continued to serve requests, whether the correct rail decisions were emitted, whether the judge tier degraded correctly, whether the circuit breaker tripped when expected, whether the frontier sampling rate adjusted downward, whether any judge drift alert fired because the effective sample rate dropped. For each of these, a yes or no with a supporting trace ID from the run.

**Presentation.** A three-row table. Rows are the three scenarios. Columns are the expected behaviors. Every cell is yes or no with a trace reference.

**Consequence to look for.** Any no in the table is a fix that gets made before the writeup is called done. A row of yeses is the strongest evidence in the writeup that the platform actually holds up.

## The Cohen's kappa threshold sweep (Day 6)

Smaller experiment, same shape.

**Question.** What kappa threshold should trigger the drift alert, given the false-block-rate budget we can tolerate on human-verified correct responses.

**Setup.** Split the FinanceBench golden set into calibration and holdout. On the holdout, simulate judge behavior at kappa thresholds from 0.4 to 0.8 in steps of 0.05. At each threshold, measure the false-block rate on responses the golden set marks correct.

**Presentation.** One line chart with threshold on the x-axis and false-block rate on the y-axis. Mark the chosen threshold with an annotation.

**Finding sentence to look for.** "Below 0.55 the false-block rate exceeded X percent, above 0.65 it dropped near zero, so 0.60 was chosen as the default drift threshold." Fill in the actual X. If the numbers turn out differently, the sentence and the chosen threshold change.

**Consequence.** The platform's default drift threshold is set based on this experiment. The kappa value in the code and in `config/calibration.yml` matches the finding. The writeup includes the sweep chart.

## The writeup lives in the README

Every experiment's five-part finding lands in the README under a section called "Findings." The section reads from top to bottom in the order the experiments were run. Do not embed findings inside long prose explanations. Interviewers skim. Give them the five parts and let the numbers speak.

If a finding was surprising, note the expected result and the actual result side by side. A candidate who says "I expected X, got Y, changed my mind because of Z" is a candidate who has actually run experiments and learned from them. That is the signal we want the writeup to send.

## Do not fake numbers under any circumstance

If an experiment fails to run because of a bug or a time constraint, say so in the writeup. "The load test scenario for two of three failure modes ran cleanly. The Redpanda backpressure scenario was not completed before deadline, and is documented as a known gap." That is a stronger signal than a made-up number, because it shows judgment, and because a hiring manager who catches a made-up number will not forgive it.

Every number in the README traces back to a script in `experiments/` that produced it. The scripts are checked in. The output files are checked in. The charts are generated from the output files, not hand-drawn.

## Verification checklist before you say a finding is done

1. All five parts are present in the writeup.
2. Every number in the writeup traces to a script and an output file in `experiments/`.
3. Every chart is generated by a checked-in script and reproducible.
4. The consequence, if any, is reflected in the code and configuration.
5. If the finding conflicts with what the spec assumed, either the spec's assumption was right and this is documented, or the platform's behavior changed to match reality.

A finding without a script behind it is a claim without evidence. Not acceptable in the writeup.
