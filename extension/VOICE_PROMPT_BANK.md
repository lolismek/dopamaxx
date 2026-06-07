# DopaMAXX Voice Prompt Bank

This first pass defines 36 fixed prompts with stable IDs and generated audio filenames. The lines are written for a low, dry radio-announcer delivery, but they avoid dependency on a specific real person's voice.

Preview WAV assets live in `assets/voice_prompts/` and were generated with the local Windows `Microsoft Zira Desktop` voice at rate `-6`, then processed through a haunted shortwave chain: slight pitch drop, mono 22.05 kHz output, high-pass, low-pass, heavy compression, bit crushing, ghost echo, limiting, white static, brown rumble, carrier whine, and low hum. Regenerate them with:

```powershell
powershell -ExecutionPolicy Bypass -File extension\scripts\generate_voice_prompts.ps1
```

| ID | Event | Filename | Prompt |
| --- | --- | --- | --- |
| blocked_001 | blocked_site_locked_in | blocked_001_lock_the_fuck_in_gi.wav | Lock the fuck in, GI. That site can wait. |
| blocked_002 | blocked_site_locked_in | blocked_002_not_the_mission.wav | Eyes forward, GI. This is not the mission. |
| blocked_003 | blocked_site_locked_in | blocked_003_hold_the_line.wav | Hold the line, GI. Do not wander off post. |
| blocked_004 | blocked_site_locked_in | blocked_004_not_now.wav | Not now, GI. Your work window is still active. |
| blocked_005 | blocked_site_locked_in | blocked_005_stay_on_signal.wav | Stay on signal, GI. The noise is trying to pull you out. |
| blocked_006 | blocked_site_locked_in | blocked_006_no_rabbit_holes.wav | Negative, GI. No rabbit holes during locked-in time. |
| blocked_007 | blocked_site_locked_in | blocked_007_back_to_work.wav | Back to work, GI. The break is not here yet. |
| blocked_008 | blocked_site_locked_in | blocked_008_signal_before_comfort.wav | Signal before comfort, GI. Eyes back on the task. |
| blocked_009 | blocked_site_locked_in | blocked_009_leave_it_closed.wav | Leave it closed, GI. Your future self is watching. |
| blocked_010 | blocked_site_locked_in | blocked_010_hold_your_position.wav | Hold your position, GI. Finish the minute in front of you. |
| blocked_011 | blocked_site_locked_in | blocked_011_distraction_denied.wav | Distraction denied, GI. Return to the objective. |
| blocked_012 | blocked_site_locked_in | blocked_012_stay_locked.wav | Stay locked, GI. The dopamine trap can wait. |
| locked_in_001 | locked_in_started | locked_in_001_back_to_post.wav | Back to post, GI. Lock in. |
| locked_in_002 | locked_in_started | locked_in_002_wire_is_live.wav | The wire is live, GI. Eyes on the work. |
| locked_in_003 | locked_in_started | locked_in_003_focus_window_open.wav | Focus window is open. Hold steady, GI. |
| locked_in_004 | locked_in_started | locked_in_004_entering_locked_in.wav | Entering locked-in time. Keep the channel clean, GI. |
| locked_in_005 | locked_in_started | locked_in_005_work_mode_active.wav | Work mode active, GI. Calm mind, clean hands. |
| locked_in_006 | locked_in_started | locked_in_006_you_know_the_drill.wav | You know the drill, GI. One task, no drift. |
| locked_in_007 | locked_in_started | locked_in_007_station_is_open.wav | The station is open, GI. Send only focus. |
| locked_in_008 | locked_in_started | locked_in_008_make_it_quiet.wav | Make it quiet, GI. Let the work get loud. |
| locked_out_001 | locked_out_started | locked_out_001_good_work_take_a_break.wav | Good work. Take a break, GI. |
| locked_out_002 | locked_out_started | locked_out_002_stand_down.wav | Stand down, GI. You earned the interval. |
| locked_out_003 | locked_out_started | locked_out_003_break_window_open.wav | Break window is open. Breathe easy, GI. |
| locked_out_004 | locked_out_started | locked_out_004_signal_held.wav | Signal held. Good work, GI. Step away for a minute. |
| locked_out_005 | locked_out_started | locked_out_005_rest_is_authorized.wav | Rest is authorized, GI. Do not waste it. |
| locked_out_006 | locked_out_started | locked_out_006_you_made_the_cut.wav | You made the mark, GI. Take the pressure off. |
| locked_out_007 | locked_out_started | locked_out_007_clear_to_roam.wav | Clear to roam, GI. Come back sharp. |
| locked_out_008 | locked_out_started | locked_out_008_brain_gets_air.wav | The brain gets air now, GI. Good discipline. |
| microdose_001 | microdose_started | microdose_001_small_dose.wav | Small dose, GI. Clean effort only. |
| microdose_002 | microdose_started | microdose_002_keep_signal_smooth.wav | Microdose window. Keep the signal smooth, GI. |
| microdose_003 | microdose_started | microdose_003_light_touch.wav | Light touch, GI. Do not chase the feeling. |
| microdose_004 | microdose_started | microdose_004_notice_the_shift.wav | Notice the shift, GI. Then get back to the work. |
| reengaged_001 | reengaged | reengaged_001_back_on_signal.wav | You are back on signal, GI. |
| reengaged_002 | reengaged | reengaged_002_good_recovery.wav | Good recovery, GI. Stay with it. |
| reengaged_003 | reengaged | reengaged_003_drift_corrected.wav | Drift corrected, GI. Keep the heading. |
| reengaged_004 | reengaged | reengaged_004_signal_returning.wav | Signal is returning, GI. Hold steady. |
