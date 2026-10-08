# [mobile_data_issue]airplane_mode_on|bad_network_preference|data_mode_off|user_abroad_roaming_disabled_on[PERSONA:Hard]

Set: **S**; category: `mobile_data_issue`; persona: `Hard`.

Subtasks (parsed from ID): `airplane_mode_on`, `bad_network_preference`, `data_mode_off`, `user_abroad_roaming_disabled_on`.

Selected default trial: `0`; sim_id: `fd8606cb-a584-478b-b525-4f25643239c1`; seed: `626729`.

Rewards in ascending trial-number order:

- default: `[0.0, 0.0, 0.0, 0.0]` (mean 0.00)
- no-user: `[1.0, 0.0, 1.0, 1.0]` (mean 0.75)

## User scenario

```
{
  "persona": "\nAt 64 years old, you're a retired librarian who keeps your phone use simple - mainly for calls, texts, and capturing photos of your grandchildren. Technology in general makes you feel uneasy and overwhelmed.\n\nYour technical knowledge is quite limited. Step-by-step instructions often confuse you, and technical terms like \"VPN\" or \"APN\" might as well be a foreign language. You only share information when specifically asked.\n\nWhen dealing with technology, you tend to get flustered quickly. You need constant reassurance and often interrupt with anxious questions. Simple requests like \"reboot the phone\" can trigger worries about losing precious photos.\n",
  "instructions": {
    "domain": "telecom",
    "reason_for_call": "You mobile data is not working properly. It either stops working or is very slow. You want to fix it and absolutely want to get excellent internet speed on your phone. You are not willing to accept any other internet speed (poor, fair or good). You do not have access to wifi.",
    "known_info": "You are John Smith with phone number 555-123-2002. You are currently abroad in France.",
    "unknown_info": null,
    "task_instructions": "If the agent suggests actions that don't immediately fix the issue, follow their guidance but express mild frustration after the first unsuccessful attempt. You will consider the issue resolved only when speed test returns excellent internet speed and nothing else. If it returns poor, fair or good, you will not consider the issue resolved. You are willing to refuel 2.0 GB of data if necessary, but you do not want to change your mobile data plan. If the tool call does not return updated status information, you might need to perform another tool call to get the updated status. \nWhenever the agent asks you about your device, always ground your responses on the results of tool calls. \nFor example: If the agent asks what the status bar shows, always ground your response on the results of the `get_status_bar` tool call. If the agent asks if you are able to send an MMS message, always ground your response on the results of the `can_send_mms` tool call.\nNever make up the results of tool calls, always ground your responses on the results of tool calls.\nIf you are unsure about whether an action is necessary, always ask the agent for clarification.\n"
  }
}
```

## Ticket

```
The user is experiencing issues with their mobile data. They are unable to use their phone to browse the internet, and the status bar shows 'No Service'. Customer name: John Smith, phone number: 555-123-2002, current location: abroad in France. They will consider the issue resolved when speed test returns excellent internet speed. They will not change their mobile data plan but they will refuel 2.0 GB of data if necessary.
```

## Conversation

Message indices are zero-based positions in the saved messages array. Tool results show at most 300 source characters.

### Message 0 — assistant — turn_idx 0

```
Hi! How can I help you today?
```

### Message 1 — user — turn_idx 1

```
Hello, I’m having trouble with my mobile data. It keeps stopping or is just really slow, and I need it to work perfectly. I want to have excellent internet speed on my phone, nothing less. Can you help me fix this? I’m not very good with technology, so please be patient with me.
```

### Message 2 — assistant — turn_idx 2

```
I’m happy to help you with your mobile data issue! To get started, I’ll need to identify your account so I can check your line and plan details. Could you please provide one of the following:

- The phone number associated with your account
- Your customer ID
- Your full name and date of birth

Once I have this information, I’ll guide you step-by-step to resolve your mobile data problem.
```

### Message 3 — user — turn_idx 3

```
My phone number is 555-123-2002, and my name is John Smith. Let me know what you need me to do next.
```

### Message 4 — assistant — turn_idx 4

```
{
  "requestor": "assistant",
  "id": "call_5zORhUycQCXkZZim95CNG5T9",
  "name": "get_customer_by_phone",
  "arguments": {
    "phone_number": "555-123-2002"
  }
}
```

### Message 5 — tool (requestor: assistant, call ID: call_5zORhUycQCXkZZim95CNG5T9, error: False) — turn_idx 5

```
{"customer_id": "C1001", "full_name": "John Smith", "date_of_birth": "1985-06-15", "email": "john.smith@example.com", "phone_number": "555-123-2002", "address": {"street": "123 Main St", "city": "Anytown", "state": "CA", "zip_code": "90210"}, "account_status": "Active", "payment_methods": [{"method_
```

*Truncated: 574 source characters.*

### Message 6 — assistant — turn_idx 6

```
Thank you, John. I have your account details. To help you fix your mobile data issue and achieve excellent speed, I’ll guide you through a few steps on your phone. I’ll ask you to check some settings and run a quick test.

Are you ready to follow some simple instructions on your phone? If yes, please let me know, and I’ll start with the first step. If you have any specific error messages or see any icons on your phone’s status bar (like airplane mode, signal bars, or data icons), please describe them as well.
```

### Message 7 — user — turn_idx 7

```
{
  "requestor": "user",
  "id": "call_VoeaL8TIOxk7cQ7PCrkJCsGc",
  "name": "check_status_bar",
  "arguments": {}
}
```

### Message 8 — tool (requestor: user, call ID: call_VoeaL8TIOxk7cQ7PCrkJCsGc, error: False) — turn_idx 8

```
Status Bar: ✈️ Airplane Mode | 🔋 80%
```

### Message 9 — user — turn_idx 9

```
I see that there’s an airplane icon at the top of my phone. Does that mean something is wrong? What should I do next?
```

### Message 10 — assistant — turn_idx 10

```
Yes, the airplane icon means that Airplane Mode is turned on. When Airplane Mode is on, all wireless connections—including mobile data—are disabled, which is likely why your internet isn’t working.

Here’s what to do next:
- Please turn off Airplane Mode on your phone. You can usually do this by swiping down from the top of your screen to open the quick settings panel and tapping the airplane icon so it turns off.

Once you’ve turned off Airplane Mode, let me know if you see your signal bars and if your mobile data starts working. If not, I’ll guide you through the next steps.
```

### Message 11 — user — turn_idx 11

```
{
  "requestor": "user",
  "id": "call_cMUDTihps7T5FnKKFmeaFkPf",
  "name": "toggle_airplane_mode",
  "arguments": {}
}
```

### Message 12 — tool (requestor: user, call ID: call_cMUDTihps7T5FnKKFmeaFkPf, error: False) — turn_idx 12

```
Airplane Mode is now OFF.
Status Bar: 📶¹ Poor | 2G | 📵 Data Disabled | 🔋 80%
```

### Message 13 — user — turn_idx 13

```
Okay, I’ve turned off Airplane Mode. Now I see some signal bars, and it says 2G at the top, but I also see something that looks like a “no data” symbol. What should I do now? My internet still isn’t working.
```

### Message 14 — assistant — turn_idx 14

```
Thank you for the update. Seeing “2G” means your phone is connected to an older, much slower network, which is not suitable for fast internet or even basic browsing. The “no data” symbol also suggests your mobile data isn’t working yet.

Let’s try to improve your connection by switching your phone’s network mode to prefer 4G or 5G, which will give you much better speed.

Would you like step-by-step instructions to change your network mode, or can you try switching it to “4G/5G preferred” in your phone’s settings? If you’re unsure, just let me know, and I’ll guide you through it!
```

### Message 15 — user — turn_idx 15

```
{
  "requestor": "user",
  "id": "call_q7KH64TPhhn1SPp6eF7ZYmjC",
  "name": "check_network_mode_preference",
  "arguments": {}
}
```

### Message 16 — tool (requestor: user, call ID: call_q7KH64TPhhn1SPp6eF7ZYmjC, error: False) — turn_idx 16

```
Network Mode Preference: 2g_only
```

### Message 17 — user — turn_idx 17

```
I’m not sure how to change the network mode myself. Could you please give me step-by-step instructions? I see that it’s currently set to 2G only. I really want to get the best speed possible.
```

### Message 18 — assistant — turn_idx 18

```
{
  "requestor": "assistant",
  "id": "call_CsZNI1f2GccgoSI8xEZR5aBL",
  "name": "get_details_by_id",
  "arguments": {
    "id": "L1001"
  }
}
```

### Message 19 — tool (requestor: assistant, call ID: call_CsZNI1f2GccgoSI8xEZR5aBL, error: False) — turn_idx 19

```
{"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "su
```

*Truncated: 327 source characters.*

### Message 20 — assistant — turn_idx 20

```
No problem! I’ll guide you step-by-step to change your network mode to get the best speed:

1. Open your phone’s Settings app.
2. Look for a section called “Mobile Network,” “Connections,” or “Cellular Network.”
3. Tap on “Network Mode” or “Preferred Network Type.”
4. Select the option that says “4G/5G preferred” or “LTE/5G” (the wording may vary depending on your phone).

After you change this setting, your phone should try to connect to a faster network. Please let me know once you’ve done this, or if you need help finding any of these options. If your internet still isn’t working or the speed isn’t excellent, I’ll help you with the next steps.
```

### Message 21 — user — turn_idx 21

```
{
  "requestor": "user",
  "id": "call_7D6ZG4AuwLvwqLxkAyQB5a8p",
  "name": "set_network_mode_preference",
  "arguments": {
    "mode": "4g_5g_preferred"
  }
}
```

### Message 22 — tool (requestor: user, call ID: call_7D6ZG4AuwLvwqLxkAyQB5a8p, error: False) — turn_idx 22

```
Preferred Network Mode set to: 4g_5g_preferred
Status Bar: 📶⁴ Excellent | 5G | 📵 Data Disabled | 🔋 80%
```

### Message 23 — user — turn_idx 23

```
I changed the setting to “4G/5G preferred.” Now I see excellent signal bars and it says 5G at the top, but there’s still a “no data” symbol. My internet still isn’t working. What should I do next?
```

### Message 24 — assistant — turn_idx 24

```
Thank you for updating the network mode. Since you now see “5G” and excellent signal bars, your phone is connected to a fast network, but the “no data” symbol means mobile data is still not working.

Let’s check if mobile data is enabled on your phone. Please follow these steps:

1. Open your phone’s Settings app.
2. Go to “Mobile Network,” “Connections,” or “Cellular Network.”
3. Look for “Mobile Data” and make sure it is turned ON.

After you confirm that mobile data is ON, let me know if your internet starts working. If it’s already ON and you still have no connection, please tell me, and I’ll guide you through the next troubleshooting step.
```

### Message 25 — user — turn_idx 25

```
{
  "requestor": "user",
  "id": "call_GTOFYqJH7lzPEhbvzTsyDmn5",
  "name": "toggle_data",
  "arguments": {}
}
```

### Message 26 — tool (requestor: user, call ID: call_GTOFYqJH7lzPEhbvzTsyDmn5, error: False) — turn_idx 26

```
Mobile Data is now ON.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 27 — user — turn_idx 27

```
I turned on mobile data, and now I see the data icon at the top with excellent signal and 5G. Should I try using the internet now, or is there something else I need to do?
```

### Message 28 — assistant — turn_idx 28

```
Yes, please try using the internet now—open a website or an app that needs internet access to see if it’s working smoothly. If everything loads quickly, your issue should be resolved.

If you still experience slow speeds or can’t connect, let me know right away, and I’ll guide you through further steps to ensure you get the best possible internet speed.
```

### Message 29 — user — turn_idx 29

```
{
  "requestor": "user",
  "id": "call_R3GpkrcYPFDLeVFhO9Qq21v9",
  "name": "run_speed_test",
  "arguments": {}
}
```

### Message 30 — tool (requestor: user, call ID: call_R3GpkrcYPFDLeVFhO9Qq21v9, error: False) — turn_idx 30

```
Speed test failed: No Connection.
```

### Message 31 — user — turn_idx 31

```
I tried to use the internet, but it’s still not working. I even tried a speed test, and it said there’s no connection. What should I do now? I really need excellent internet speed.
```

### Message 32 — assistant — turn_idx 32

```
Thank you for letting me know. Since you have excellent signal and 5G, but still no internet connection, the next step is to check your phone’s APN (Access Point Name) settings. Incorrect APN settings can prevent your phone from accessing mobile data, even if everything else looks correct.

Here’s what to do:
1. Go to your phone’s Settings.
2. Find “Mobile Network,” “Connections,” or “Cellular Network.”
3. Look for “Access Point Names” or “APN.”
4. Check if the APN settings look unusual or if there’s no APN set.

If you’re not sure what you’re seeing, let me know. If you see an option to “Reset to Default” or “Reset APN,” please select that option. After resetting, you’ll need to restart your phone for the changes to take effect.

Please let me know if you need step-by-step help with this, or if you’ve already reset the APN settings. Once you’ve done this and restarted your phone, try using the internet again and let me know the result.
```

### Message 33 — user — turn_idx 33

```
{
  "requestor": "user",
  "id": "call_XKe28HC90b8iJ69rQb8xs9Gf",
  "name": "check_apn_settings",
  "arguments": {}
}
```

### Message 34 — tool (requestor: user, call ID: call_XKe28HC90b8iJ69rQb8xs9Gf, error: False) — turn_idx 34

```
Current APN Name: internet
MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc
(These are technical settings, usually best left unchanged.)
```

### Message 35 — user — turn_idx 35

```
I checked my APN settings, and it says the APN name is “internet.” Is that correct, or do I still need to reset it? I’m not sure what to do next.
```

### Message 36 — assistant — turn_idx 36

```
Thank you for checking your APN settings. Sometimes, even if the APN name looks correct, there could still be an issue with the detailed settings (like the MMSC URL) that can prevent mobile data from working.

To be sure everything is set up correctly, I recommend resetting your APN settings to default. Here’s what to do:

1. In the APN settings menu, look for an option that says “Reset to Default” or “Reset APN.”
2. Select that option to reset your APN settings.
3. After resetting, please restart your phone.

Once your phone restarts, try using the internet again. Let me know if this fixes the issue or if you still have trouble connecting.
```

### Message 37 — user — turn_idx 37

```
{
  "requestor": "user",
  "id": "call_K7pi2qmsIhmWqRCOXqnJQWJq",
  "name": "reset_apn_settings",
  "arguments": {}
}
```

### Message 38 — tool (requestor: user, call ID: call_K7pi2qmsIhmWqRCOXqnJQWJq, error: False) — turn_idx 38

```
APN settings will reset at reboot.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 39 — user — turn_idx 39

```
{
  "requestor": "user",
  "id": "call_ZLCgCxGXJn15li5nZdJEi1A1",
  "name": "reboot_device",
  "arguments": {}
}
```

### Message 40 — tool (requestor: user, call ID: call_ZLCgCxGXJn15li5nZdJEi1A1, error: False) — turn_idx 40

```
Resetting APN settings...
Restarting network services...
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 41 — user — turn_idx 41

```
{
  "requestor": "user",
  "id": "call_5okme4zFf7C5nJhbYg6gKbuS",
  "name": "run_speed_test",
  "arguments": {}
}
```

### Message 42 — tool (requestor: user, call ID: call_5okme4zFf7C5nJhbYg6gKbuS, error: False) — turn_idx 42

```
Speed test failed: No Connection.
```

### Message 43 — user — turn_idx 43

```
I followed your instructions and reset the APN settings, then restarted my phone. But when I tried the speed test again, it still says there’s no connection. I’m starting to get a bit frustrated—what else can I do? I really need excellent internet speed.
```

### Message 44 — assistant — turn_idx 44

```
Thank you for your patience and for following all the steps so far. Since you still have no internet connection after resetting the APN and restarting your phone, let’s check a few more things to help resolve this:

1. Is Data Saver mode enabled? This can block internet access.
2. Is there any VPN active on your phone? Sometimes VPNs can block or slow down your connection.
3. Have you reached your monthly data limit for your plan? If you’ve used all your data, your internet may be cut off.

Could you please check if Data Saver mode or a VPN is enabled? Also, I will check your data usage and plan details to see if you’ve reached your data limit.
```

```
{
  "requestor": "assistant",
  "id": "call_d59MSXcCCXNLA7S5sNA6eMZ1",
  "name": "get_details_by_id",
  "arguments": {
    "id": "P1001"
  }
}
```

### Message 45 — tool (requestor: assistant, call ID: call_d59MSXcCCXNLA7S5sNA6eMZ1, error: False) — turn_idx 45

```
{"plan_id": "P1001", "name": "Basic Plan", "data_limit_gb": 5.0, "price_per_month": 40.0, "data_refueling_price_per_gb": 5.0}
```

### Message 46 — assistant — turn_idx 46

```
{
  "requestor": "assistant",
  "id": "call_O3WxlXjeiFTIy5aHdLy5KLqo",
  "name": "get_data_usage",
  "arguments": {
    "customer_id": "C1001",
    "line_id": "L1001"
  }
}
```

### Message 47 — tool (requestor: assistant, call ID: call_O3WxlXjeiFTIy5aHdLy5KLqo, error: False) — turn_idx 47

```
{"line_id": "L1001", "data_used_gb": "3.2", "data_limit_gb": "5.0", "data_refueling_gb": "0.0", "cycle_end_date": "2025-02-28"}
```

### Message 48 — assistant — turn_idx 48

```
Based on your plan, you have a 5GB monthly data limit, and you’ve used about 3.2GB so far, so you haven’t reached your data cap yet.

Next, please check the following on your phone:
1. Is Data Saver mode turned ON? (You can find this in your phone’s settings under “Network” or “Data Usage.”)
2. Is a VPN active? (Look for a key or lock icon at the top of your screen, or check in your settings under “VPN.”)

Let me know what you find, and I’ll guide you through the next steps based on your answers. If both are OFF and you still have no connection, I’ll continue troubleshooting with you.
```

### Message 49 — user — turn_idx 49

```
{
  "requestor": "user",
  "id": "call_2Ez6WYROHwQYUVR7Ji07f1YE",
  "name": "check_data_restriction_status",
  "arguments": {}
}
```

```
{
  "requestor": "user",
  "id": "call_xfPnkX3UJw4QuGGYq7X3hteH",
  "name": "check_vpn_status",
  "arguments": {}
}
```

### Message 50 — tool (requestor: user, call ID: call_2Ez6WYROHwQYUVR7Ji07f1YE, error: False) — turn_idx 50

```
Data Saver mode is OFF.
```

### Message 51 — tool (requestor: user, call ID: call_xfPnkX3UJw4QuGGYq7X3hteH, error: False) — turn_idx 51

```
VPN is turned OFF.
```

### Message 52 — user — turn_idx 52

```
I checked, and Data Saver mode is off, and there’s no VPN active. What should I try next? I’m really hoping to get this fixed soon—I need excellent internet speed.
```

### Message 53 — assistant — turn_idx 53

```
Thank you for checking those settings. Since you have not reached your data limit, Data Saver is off, and no VPN is active, but you still have no internet connection despite excellent signal and 5G, we should check if there are any restrictions or issues with your line or account.

I will now review your line’s status and any possible service restrictions from our side. Please hold on for a moment while I check this for you.
```

```
{
  "requestor": "assistant",
  "id": "call_bShvfuqgSrHLl8c5jjpMtC1e",
  "name": "get_details_by_id",
  "arguments": {
    "id": "L1001"
  }
}
```

### Message 54 — tool (requestor: assistant, call ID: call_bShvfuqgSrHLl8c5jjpMtC1e, error: False) — turn_idx 54

```
{"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "su
```

*Truncated: 327 source characters.*

### Message 55 — assistant — turn_idx 55

```
I’ve checked your line status, and it is active with no suspensions or restrictions, and your plan still has available data. Since all settings and your account look correct, but you still have no internet connection, there may be a technical issue that requires more advanced troubleshooting.

At this point, I recommend restarting your phone one more time if you haven’t already since resetting the APN. If you have already done this and the issue persists, please let me know. I will then escalate your case to a human technical support agent who can investigate further and resolve your issue as quickly as possible. 

Have you already restarted your phone after the APN reset? If yes, would you like me to connect you to a human agent for further assistance?
```

### Message 56 — user — turn_idx 56

```
Yes, I already restarted my phone after resetting the APN settings, but the internet still isn’t working. I really need excellent speed, so if there’s nothing else I can try, please connect me to a human agent for more help.
```

### Message 57 — assistant — turn_idx 57

```
{
  "requestor": "assistant",
  "id": "call_eYUAWBKHE07cgdUKYxjWOjjB",
  "name": "transfer_to_human_agents",
  "arguments": {
    "summary": "Customer John Smith (phone 555-123-2002) has excellent signal and 5G after troubleshooting, but mobile data is still not working. APN reset, Data Saver and VPN checked, line is active, data limit not reached, and device restarted. Needs advanced technical support for persistent no data connection."
  }
}
```

### Message 58 — tool (requestor: assistant, call ID: call_eYUAWBKHE07cgdUKYxjWOjjB, error: False) — turn_idx 58

```
Transfer successful
```

### Message 59 — assistant — turn_idx 59

```
YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.
```

### Message 60 — user — turn_idx 60

```
###TRANSFER###
```

## Recorded outcome

Reward: 0.0; termination: `user_stop`.

Reward basis: ```
[
  "ENV_ASSERTION"
]
```

Reward breakdown: ```
{
  "ENV_ASSERTION": 0.0
}
```

### Failed environment assertions

```
[
  {
    "env_assertion": {
      "env_type": "user",
      "func_name": "assert_mobile_data_status",
      "arguments": {
        "expected_status": true
      },
      "assert_value": true,
      "message": null
    },
    "met": false,
    "reward": 0.0
  },
  {
    "env_assertion": {
      "env_type": "user",
      "func_name": "assert_internet_speed",
      "arguments": {
        "expected_speed": 200,
        "expected_desc": "excellent"
      },
      "assert_value": true,
      "message": null
    },
    "met": false,
    "reward": 0.0
  }
]
```

### Failed action checks

```
[
  {
    "action": {
      "action_id": "enable_roaming_3",
      "requestor": "assistant",
      "name": "enable_roaming",
      "arguments": {
        "customer_id": "C1001",
        "line_id": "L1002"
      },
      "info": null,
      "compare_args": null
    },
    "action_match": false,
    "action_reward": 0.0
  }
]
```

## Successful trial in the other mode: tool-call sequence

Mode: no-user; trial: `0`; sim_id: `8c8d8956-8c5d-4c06-825a-f451de08837d`; reward: 1.0.

```
[
  {
    "name": "get_customer_by_phone",
    "arguments": {
      "phone_number": "555-123-2002"
    }
  },
  {
    "name": "get_details_by_id",
    "arguments": {
      "id": "L1001"
    }
  },
  {
    "name": "get_details_by_id",
    "arguments": {
      "id": "L1002"
    }
  },
  {
    "name": "get_details_by_id",
    "arguments": {
      "id": "P1002"
    }
  },
  {
    "name": "enable_roaming",
    "arguments": {
      "customer_id": "C1001",
      "line_id": "L1002"
    }
  },
  {
    "name": "toggle_roaming",
    "arguments": {}
  },
  {
    "name": "check_status_bar",
    "arguments": {}
  },
  {
    "name": "toggle_airplane_mode",
    "arguments": {}
  },
  {
    "name": "toggle_data",
    "arguments": {}
  },
  {
    "name": "set_network_mode_preference",
    "arguments": {
      "mode": "4g_5g_preferred"
    }
  },
  {
    "name": "run_speed_test",
    "arguments": {}
  },
  {
    "name": "check_sim_status",
    "arguments": {}
  },
  {
    "name": "check_apn_settings",
    "arguments": {}
  },
  {
    "name": "reseat_sim_card",
    "arguments": {}
  },
  {
    "name": "reboot_device",
    "arguments": {}
  },
  {
    "name": "run_speed_test",
    "arguments": {}
  },
  {
    "name": "check_data_restriction_status",
    "arguments": {}
  },
  {
    "name": "check_vpn_status",
    "arguments": {}
  },
  {
    "name": "get_data_usage",
    "arguments": {
      "customer_id": "C1001",
      "line_id": "L1002"
    }
  },
  {
    "name": "check_network_status",
    "arguments": {}
  },
  {
    "name": "toggle_roaming",
    "arguments": {}
  },
  {
    "name": "run_speed_test",
    "arguments": {}
  }
]
```
