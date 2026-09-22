# SyncCut User Study Task Protocol & Script

## Study Overview
- **Goal**: Compare video editor speed, accuracy, and perceived workload when synchronizing multi-camera footage manually vs using SyncCut.
- **Participants**: Professional video editors and content creators ($N \ge 10$).
- **Design**: Within-subject counterbalanced design (Condition A: Manual Sync in NLE vs Condition B: SyncCut Automated Sync).

## Task Protocol
1. **Introduction & Consent** (5 min): Explain study scope and obtain informed consent.
2. **Task 1: Manual Synchronization** (15 min max):
   - Participant receives 4 unsynchronized camera angles + 1 reference audio track.
   - Goal: Align all tracks in DaVinci Resolve / Premiere Pro manually by waveform matching or slate visual cues.
   - Researcher records time-to-completion and remaining sync errors (in frames).
3. **Task 2: SyncCut Automated Synchronization** (5 min):
   - Participant runs SyncCut GUI or CLI on the same or equivalent 4-camera dataset.
   - Inspect confidence badges, review flagged items, nudge if needed, and export FCPXML timeline.
   - Import FCPXML into NLE and confirm alignment.
4. **Post-Task Questionnaires** (10 min):
   - Complete System Usability Scale (SUS).
   - Complete NASA Task Load Index (NASA-TLX).
   - Answer Willingness-To-Pay (WTP) valuation questions.
