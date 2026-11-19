# Reading the charts on CHIP profiles

Each section of a CHIP profile opens with a chart panel showing the published figures for your area. Every chart displays numbers as the source agency publishes them, with no added scores, composites, or calculated differences between periods.

## The dot and its interval

A blue circle marks the published estimate for your county, state, or congressional district. When a source publishes sampling uncertainty, a horizontal bar extends through the dot to show that range—either a 95% confidence interval (CDC PLACES and BRFSS) or a 90% margin of error (Census ACS). A wider bar reflects greater statistical uncertainty, which is common in smaller populations. Sources that do not publish sampling intervals (CMS Medicare, HRSA, AHRQ, USDA, and EPA) appear as a dot alone. When a figure is unavailable, CHIP displays the source's status note and never substitutes zero.

## State and U.S. markers

When a source publishes comparable figures on the same scale for the same period, reference markers appear on the chart axis:

- **Gold diamond:** the state figure.
- **Teal square:** the U.S. figure.

These markers are omitted in two situations:

- **Count measures** (such as total population, Medicare beneficiaries, physicians, dentists, hospitals, beds, or air-quality days), because an area's total cannot share a scale with a state or national total.
- **Sources without comparable state or national estimates**, including HRSA AHRF, AHRQ CLH, EPA Air Quality, USDA Food Environment Atlas, and U.S. figures for BRFSS (CDC publishes a median of states, which is not a national survey estimate).

## Why PLACES counties are compared only with other counties

CDC PLACES county figures are model-based estimates, while CDC BRFSS state figures come directly from state survey responses. Because modeled estimates and direct survey estimates are produced differently, CHIP never places them on the same chart axis. Instead, each PLACES row shows your county alongside other counties in the same state from the same PLACES model and release. The state's BRFSS figure appears only as a separate labelled note for context.

## Reading figures over time

Opening **Over time** shows earlier published periods where two or more periods exist (congressional districts have no earlier periods on CHIP).

- **PLACES years are separate dots with no line.** Each year comes from a separate PLACES release and model run with its own methods and inputs. Because CDC advises caution when comparing across releases, each year is shown as an unconnected dot with its 95% confidence interval and release label.
- **ACS 5-year windows overlap.** Neighbouring ACS periods (such as 2019–2023 and 2020–2024) share four of their five survey years, so adjacent points are not independent annual measurements. Median income windows are also inflation-adjusted to each window's own final year.
- **Boundary breaks.** When geographic boundaries change between periods, any line breaks at that boundary change and displays the period's note.

## Overlapping intervals are not a significance test

Checking whether two intervals overlap is a visual aid, not a statistical significance test. Estimates whose intervals touch or slightly overlap can still differ statistically, and non-overlapping intervals alone do not show a cause or practical effect.
