import { useEffect } from 'react';
import { Joyride, STATUS, type Step } from 'react-joyride';

interface OnboardingTourProps {
  run: boolean;
  onRunChange: (run: boolean) => void;
}

const STEPS: Step[] = [
  {
    target: '[data-tour="media-pool"]',
    title: 'Media Pool',
    content: 'Your imported camera and audio assets are listed here.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="media-import"]',
    title: 'Import Media',
    content: 'Import your camera files to sync them and build an editable program timeline.',
    placement: 'right',
  },
  {
    target: '[data-tour="program-monitor"]',
    title: 'Program Monitor',
    content: 'Preview the camera selected by your program timeline.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="playback-controls"]',
    title: 'Playback Controls',
    content: 'Play, pause, seek, set playback speed, and adjust preview volume.',
    placement: 'top',
  },
  {
    target: '[data-tour="program-timeline"]',
    title: 'The Program Timeline',
    content: 'This is your final edited sequence.',
    placement: 'top',
  },
  {
    target: '[data-tour="program-track"]',
    title: 'Program Clips',
    content: 'The timeline contains the final camera sequence. Drag a clip to reposition it.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="program-track"]',
    title: 'Manual Override',
    content: 'Right-click a program clip to replace its camera angle.',
    placement: 'top',
  },
  {
    target: '[data-tour="inspector"]',
    title: 'Inspector',
    content: 'Adjust the selected clip’s scale, position, rotation, and opacity.',
    placement: 'left',
  },
  {
    target: '[data-tour="blade-tool"]',
    title: 'Timeline Editing',
    content: 'Split clips at the playhead, delete clips, move clips, and undo or redo edits.',
    placement: 'top',
  },
  {
    target: '[data-tour="export-button"]',
    title: 'Export',
    content: 'Export your final edit to FCPXML, Premiere, or AAF.',
    placement: 'bottom-end',
  },
];

export default function OnboardingTour({ run, onRunChange }: OnboardingTourProps) {
  useEffect(() => {
    const key = 'synccut-workspace-tour-seen';
    try {
      if (window.localStorage.getItem(key)) return;
      window.localStorage.setItem(key, 'true');
    } catch {
      // Continue with the first-visit tour when browser storage is unavailable.
    }

    const timer = window.setTimeout(() => onRunChange(true), 800);
    return () => window.clearTimeout(timer);
  }, [onRunChange]);

  return (
    <Joyride
      run={run}
      steps={STEPS}
      continuous
      scrollToFirstStep
      onEvent={(event) => {
        if (event.status === STATUS.FINISHED || event.status === STATUS.SKIPPED) {
          onRunChange(false);
        }
      }}
      options={{
        backgroundColor: '#0a0a0c',
        primaryColor: '#00E5FF',
        textColor: '#ededed',
        overlayColor: 'rgba(0, 0, 0, 0.78)',
        showProgress: true,
        buttons: ['back', 'skip', 'primary'],
        zIndex: 10000,
      }}
      styles={{
        tooltip: {
          border: '1px solid rgba(0, 229, 255, 0.35)',
          borderRadius: 12,
          boxShadow: '0 16px 48px rgba(0, 0, 0, 0.55)',
        },
        tooltipTitle: {
          color: '#ffffff',
          fontSize: 15,
          fontWeight: 700,
        },
        tooltipContent: {
          color: '#c4c4cc',
          fontSize: 13,
          lineHeight: 1.6,
        },
        buttonPrimary: {
          borderRadius: 7,
          color: '#04181c',
          fontSize: 12,
          fontWeight: 700,
        },
        buttonBack: {
          color: '#a1a1aa',
          fontSize: 12,
        },
        buttonSkip: {
          color: '#71717a',
          fontSize: 11,
        },
      }}
    />
  );
}
