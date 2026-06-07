(function (global) {
  const EVENTS = {
    BLOCKED_SITE_LOCKED_IN: "blocked_site_locked_in",
    LOCKED_IN_STARTED: "locked_in_started",
    LOCKED_OUT_STARTED: "locked_out_started",
    MICRODOSE_STARTED: "microdose_started",
    REENGAGED: "reengaged",
  };

  const STYLE = {
    cadence: "low-radio-announcer",
    rate: 0.86,
    pitch: 0.78,
    volume: 1.0,
  };

  const PROMPT_BANK = [
    {
      id: "blocked_001",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_001_lock_the_fuck_in_gi.wav",
      text: "Lock the fuck in, GI. That site can wait.",
    },
    {
      id: "blocked_002",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_002_not_the_mission.wav",
      text: "Eyes forward, GI. This is not the mission.",
    },
    {
      id: "blocked_003",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_003_hold_the_line.wav",
      text: "Hold the line, GI. Do not wander off post.",
    },
    {
      id: "blocked_004",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_004_not_now.wav",
      text: "Not now, GI. Your work window is still active.",
    },
    {
      id: "blocked_005",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_005_stay_on_signal.wav",
      text: "Stay on signal, GI. The noise is trying to pull you out.",
    },
    {
      id: "blocked_006",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_006_no_rabbit_holes.wav",
      text: "Negative, GI. No rabbit holes during locked-in time.",
    },
    {
      id: "blocked_007",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_007_back_to_work.wav",
      text: "Back to work, GI. The break is not here yet.",
    },
    {
      id: "blocked_008",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_008_signal_before_comfort.wav",
      text: "Signal before comfort, GI. Eyes back on the task.",
    },
    {
      id: "blocked_009",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_009_leave_it_closed.wav",
      text: "Leave it closed, GI. Your future self is watching.",
    },
    {
      id: "blocked_010",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_010_hold_your_position.wav",
      text: "Hold your position, GI. Finish the minute in front of you.",
    },
    {
      id: "blocked_011",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_011_distraction_denied.wav",
      text: "Distraction denied, GI. Return to the objective.",
    },
    {
      id: "blocked_012",
      event: EVENTS.BLOCKED_SITE_LOCKED_IN,
      filename: "blocked_012_stay_locked.wav",
      text: "Stay locked, GI. The dopamine trap can wait.",
    },

    {
      id: "locked_in_001",
      event: EVENTS.LOCKED_IN_STARTED,
      filename: "locked_in_001_back_to_post.wav",
      text: "Back to post, GI. Lock in.",
    },
    {
      id: "locked_in_002",
      event: EVENTS.LOCKED_IN_STARTED,
      filename: "locked_in_002_wire_is_live.wav",
      text: "The wire is live, GI. Eyes on the work.",
    },
    {
      id: "locked_in_003",
      event: EVENTS.LOCKED_IN_STARTED,
      filename: "locked_in_003_focus_window_open.wav",
      text: "Focus window is open. Hold steady, GI.",
    },
    {
      id: "locked_in_004",
      event: EVENTS.LOCKED_IN_STARTED,
      filename: "locked_in_004_entering_locked_in.wav",
      text: "Entering locked-in time. Keep the channel clean, GI.",
    },
    {
      id: "locked_in_005",
      event: EVENTS.LOCKED_IN_STARTED,
      filename: "locked_in_005_work_mode_active.wav",
      text: "Work mode active, GI. Calm mind, clean hands.",
    },
    {
      id: "locked_in_006",
      event: EVENTS.LOCKED_IN_STARTED,
      filename: "locked_in_006_you_know_the_drill.wav",
      text: "You know the drill, GI. One task, no drift.",
    },
    {
      id: "locked_in_007",
      event: EVENTS.LOCKED_IN_STARTED,
      filename: "locked_in_007_station_is_open.wav",
      text: "The station is open, GI. Send only focus.",
    },
    {
      id: "locked_in_008",
      event: EVENTS.LOCKED_IN_STARTED,
      filename: "locked_in_008_make_it_quiet.wav",
      text: "Make it quiet, GI. Let the work get loud.",
    },

    {
      id: "locked_out_001",
      event: EVENTS.LOCKED_OUT_STARTED,
      filename: "locked_out_001_good_work_take_a_break.wav",
      text: "Good work. Take a break, GI.",
    },
    {
      id: "locked_out_002",
      event: EVENTS.LOCKED_OUT_STARTED,
      filename: "locked_out_002_stand_down.wav",
      text: "Stand down, GI. You earned the interval.",
    },
    {
      id: "locked_out_003",
      event: EVENTS.LOCKED_OUT_STARTED,
      filename: "locked_out_003_break_window_open.wav",
      text: "Break window is open. Breathe easy, GI.",
    },
    {
      id: "locked_out_004",
      event: EVENTS.LOCKED_OUT_STARTED,
      filename: "locked_out_004_signal_held.wav",
      text: "Signal held. Good work, GI. Step away for a minute.",
    },
    {
      id: "locked_out_005",
      event: EVENTS.LOCKED_OUT_STARTED,
      filename: "locked_out_005_rest_is_authorized.wav",
      text: "Rest is authorized, GI. Do not waste it.",
    },
    {
      id: "locked_out_006",
      event: EVENTS.LOCKED_OUT_STARTED,
      filename: "locked_out_006_you_made_the_cut.wav",
      text: "You made the mark, GI. Take the pressure off.",
    },
    {
      id: "locked_out_007",
      event: EVENTS.LOCKED_OUT_STARTED,
      filename: "locked_out_007_clear_to_roam.wav",
      text: "Clear to roam, GI. Come back sharp.",
    },
    {
      id: "locked_out_008",
      event: EVENTS.LOCKED_OUT_STARTED,
      filename: "locked_out_008_brain_gets_air.wav",
      text: "The brain gets air now, GI. Good discipline.",
    },

    {
      id: "microdose_001",
      event: EVENTS.MICRODOSE_STARTED,
      filename: "microdose_001_small_dose.wav",
      text: "Small dose, GI. Clean effort only.",
    },
    {
      id: "microdose_002",
      event: EVENTS.MICRODOSE_STARTED,
      filename: "microdose_002_keep_signal_smooth.wav",
      text: "Microdose window. Keep the signal smooth, GI.",
    },
    {
      id: "microdose_003",
      event: EVENTS.MICRODOSE_STARTED,
      filename: "microdose_003_light_touch.wav",
      text: "Light touch, GI. Do not chase the feeling.",
    },
    {
      id: "microdose_004",
      event: EVENTS.MICRODOSE_STARTED,
      filename: "microdose_004_notice_the_shift.wav",
      text: "Notice the shift, GI. Then get back to the work.",
    },

    {
      id: "reengaged_001",
      event: EVENTS.REENGAGED,
      filename: "reengaged_001_back_on_signal.wav",
      text: "You are back on signal, GI.",
    },
    {
      id: "reengaged_002",
      event: EVENTS.REENGAGED,
      filename: "reengaged_002_good_recovery.wav",
      text: "Good recovery, GI. Stay with it.",
    },
    {
      id: "reengaged_003",
      event: EVENTS.REENGAGED,
      filename: "reengaged_003_drift_corrected.wav",
      text: "Drift corrected, GI. Keep the heading.",
    },
    {
      id: "reengaged_004",
      event: EVENTS.REENGAGED,
      filename: "reengaged_004_signal_returning.wav",
      text: "Signal is returning, GI. Hold steady.",
    },
  ];

  const PROMPTS = PROMPT_BANK.reduce((grouped, prompt) => {
    if (!grouped[prompt.event]) grouped[prompt.event] = [];
    grouped[prompt.event].push(prompt);
    return grouped;
  }, {});

  function clampIndex(rng, length) {
    const raw = Number(rng());
    if (!Number.isFinite(raw)) return 0;
    return Math.max(0, Math.min(length - 1, Math.floor(raw * length)));
  }

  function cleanToken(value, fallback) {
    const text = String(value || fallback || "")
      .replace(/[<>]/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!text) return fallback;
    return text.length > 80 ? text.slice(0, 77) + "..." : text;
  }

  function siteLabel(urlOrHost) {
    if (!urlOrHost) return "that site";
    try {
      return cleanToken(new URL(urlOrHost).hostname.replace(/^www\./, ""), "that site");
    } catch {
      return cleanToken(urlOrHost, "that site");
    }
  }

  function createPrompt(event, _context = {}, rng = Math.random) {
    const prompts = PROMPTS[event] || PROMPTS[EVENTS.REENGAGED];
    const prompt = prompts[clampIndex(rng, prompts.length)];
    return {
      ...prompt,
      assetPath: `assets/voice_prompts/${prompt.filename}`,
      ...STYLE,
    };
  }

  const api = {
    EVENTS,
    PROMPT_BANK,
    PROMPTS,
    createPrompt,
    siteLabel,
  };

  global.DopaMaxxVoicePrompts = api;

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
