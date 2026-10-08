# [mobile_data_issue]airplane_mode_on|data_mode_off|data_saver_mode_on|data_usage_exceeded|user_abroad_roaming_enabled_off[PERSONA:Hard]

Set: **S**; category: `mobile_data_issue`; persona: `Hard`.

Subtasks (parsed from ID): `airplane_mode_on`, `data_mode_off`, `data_saver_mode_on`, `data_usage_exceeded`, `user_abroad_roaming_enabled_off`.

Selected default trial: `0`; sim_id: `fc82e996-2efa-4e6e-a3f9-08371bde3f06`; seed: `626729`.

Rewards in ascending trial-number order:

- default: `[0.0, 0.0, 0.0, 0.0]` (mean 0.00)
- no-user: `[1.0, 1.0, 1.0, 1.0]` (mean 1.00)

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
Hello, I’m having trouble with my mobile data. It either stops working or is very slow, and I really need to have excellent internet speed on my phone. I’m not sure what’s wrong, but I’d like some help to fix it, please.
```

### Message 2 — assistant — turn_idx 2

```
I’m happy to help you with your mobile data issue. To get started, I’ll need to identify your account. Could you please provide one of the following:
- The phone number associated with your account,
- Your customer ID,
- Or your full name and date of birth (in YYYY-MM-DD format)?

Once I have this information, I can begin troubleshooting your mobile data problem.
```

### Message 3 — user — turn_idx 3

```
My phone number is 555-123-2002, and my name is John Smith.
```

### Message 4 — assistant — turn_idx 4

```
{
  "requestor": "assistant",
  "id": "call_fgYHNVK4pmf4uSc4a0ZcJPte",
  "name": "get_customer_by_phone",
  "arguments": {
    "phone_number": "555-123-2002"
  }
}
```

### Message 5 — tool (requestor: assistant, call ID: call_fgYHNVK4pmf4uSc4a0ZcJPte, error: False) — turn_idx 5

```
{"customer_id": "C1001", "full_name": "John Smith", "date_of_birth": "1985-06-15", "email": "john.smith@example.com", "phone_number": "555-123-2002", "address": {"street": "123 Main St", "city": "Anytown", "state": "CA", "zip_code": "90210"}, "account_status": "Active", "payment_methods": [{"method_
```

*Truncated: 574 source characters.*

### Message 6 — assistant — turn_idx 6

```
Thank you for providing your information. To help resolve your mobile data issue, I’ll need to check a few things about your account and lines. Could you please confirm which phone number or line you are experiencing the slow or non-working mobile data on? If it’s the same number you provided (555-123-2002), please confirm, or let me know if it’s a different one. 

Once confirmed, I’ll begin troubleshooting your mobile data problem.
```

### Message 7 — user — turn_idx 7

```
Yes, it’s the same number—555-123-2002. That’s the phone I’m having trouble with.
```

### Message 8 — assistant — turn_idx 8

```
{
  "requestor": "assistant",
  "id": "call_76hyW9fxFFWa6SoST5fUPHxB",
  "name": "get_details_by_id",
  "arguments": {
    "id": "L1001"
  }
}
```

### Message 9 — tool (requestor: assistant, call ID: call_76hyW9fxFFWa6SoST5fUPHxB, error: False) — turn_idx 9

```
{"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "su
```

*Truncated: 327 source characters.*

### Message 10 — assistant — turn_idx 10

```
{
  "requestor": "assistant",
  "id": "call_wv9EFpl2243GlF9dbZ10YKr7",
  "name": "get_details_by_id",
  "arguments": {
    "id": "L1002"
  }
}
```

### Message 11 — tool (requestor: assistant, call ID: call_wv9EFpl2243GlF9dbZ10YKr7, error: False) — turn_idx 11

```
{"line_id": "L1002", "phone_number": "555-123-2002", "status": "Active", "plan_id": "P1002", "device_id": "D1002", "data_used_gb": 15.1, "data_refueling_gb": 0.0, "roaming_enabled": true, "contract_end_date": "2026-12-31", "last_plan_change_date": "2024-12-15", "last_sim_replacement_date": "2025-01-
```

*Truncated: 335 source characters.*

### Message 12 — assistant — turn_idx 12

```
Thank you for confirming. I’ll guide you through some steps to diagnose and fix your mobile data issue on 555-123-2002. 

To start, could you please check your phone’s status bar and let me know:
- If you see any signal bars (and how many),
- If you see “4G,” “5G,” or another network type,
- If mobile data is enabled,
- If Airplane Mode is on.

This information will help me determine the next steps to resolve your slow or non-working mobile data.
```

### Message 13 — user — turn_idx 13

```
{
  "requestor": "user",
  "id": "call_uTh1wr83ZQxZNSggJ3tShG9E",
  "name": "check_status_bar",
  "arguments": {}
}
```

### Message 14 — tool (requestor: user, call ID: call_uTh1wr83ZQxZNSggJ3tShG9E, error: False) — turn_idx 14

```
Status Bar: ✈️ Airplane Mode | 🔋 80%
```

### Message 15 — user — turn_idx 15

```
I just checked, and it looks like Airplane Mode is turned on. What should I do next?
```

### Message 16 — assistant — turn_idx 16

```
Airplane Mode disables all wireless connections, including mobile data. To restore your mobile data, please turn Airplane Mode off on your phone. 

Once you’ve done that, check if your mobile data starts working and if your internet speed improves. Let me know if you still experience issues after turning off Airplane Mode, and I’ll guide you through further troubleshooting steps.
```

### Message 17 — user — turn_idx 17

```
{
  "requestor": "user",
  "id": "call_x2yLQbufxTqmwOL6cnJ8nVgb",
  "name": "toggle_airplane_mode",
  "arguments": {}
}
```

### Message 18 — tool (requestor: user, call ID: call_x2yLQbufxTqmwOL6cnJ8nVgb, error: False) — turn_idx 18

```
Airplane Mode is now OFF.
Status Bar: 📶⁴ Excellent | 5G | 📵 Data Disabled | 🔋 80%
```

### Message 19 — user — turn_idx 19

```
Okay, I’ve turned Airplane Mode off. Now I see signal bars and “5G” at the top, but it looks like mobile data is still disabled. What should I do next?
```

### Message 20 — assistant — turn_idx 20

```
Please enable mobile data on your phone. You can usually do this by:
- Swiping down from the top of your screen to open the quick settings menu,
- Tapping the “Mobile Data” or “Cellular Data” icon to turn it on.

Once mobile data is enabled, check if your internet connection is working and if the speed has improved. If you still have issues, let me know and I’ll assist you further.
```

### Message 21 — user — turn_idx 21

```
{
  "requestor": "user",
  "id": "call_7LSwCXzKp7AXJA3qMZaFDy40",
  "name": "toggle_data",
  "arguments": {}
}
```

### Message 22 — tool (requestor: user, call ID: call_7LSwCXzKp7AXJA3qMZaFDy40, error: False) — turn_idx 22

```
Mobile Data is now ON.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔽 Data Saver | 🔋 80%
```

### Message 23 — user — turn_idx 23

```
I’ve turned mobile data on, and now I see the signal bars, “5G,” and a little icon that says “Data Saver.” Should I check my internet speed now, or is there something else I need to do?
```

### Message 24 — assistant — turn_idx 24

```
Since you see the “Data Saver” icon, it means Data Saver mode is enabled. This mode can restrict background data and may slow down your internet experience.

Please turn off Data Saver mode in your phone’s settings. After you’ve done that, check your internet speed and let me know if your mobile data is working well or if you still notice any issues. If problems persist, I’ll guide you through the next steps.
```

### Message 25 — user — turn_idx 25

```
{
  "requestor": "user",
  "id": "call_guxOJFNsCas5JOg22G093hUe",
  "name": "toggle_data_saver_mode",
  "arguments": {}
}
```

### Message 26 — tool (requestor: user, call ID: call_guxOJFNsCas5JOg22G093hUe, error: False) — turn_idx 26

```
Data Saver Mode is now OFF.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 27 — user — turn_idx 27

```
{
  "requestor": "user",
  "id": "call_LzeAayva0Y7QzhUDW1FxfrIN",
  "name": "run_speed_test",
  "arguments": {}
}
```

### Message 28 — tool (requestor: user, call ID: call_LzeAayva0Y7QzhUDW1FxfrIN, error: False) — turn_idx 28

```
Speed test failed: No Connection.
```

### Message 29 — user — turn_idx 29

```
I turned off Data Saver mode, but when I tried to check my internet speed, it said there’s no connection. What should I do now?
```

### Message 30 — assistant — turn_idx 30

```
Thank you for letting me know. Since you’re still not getting a connection, let’s check a few more things:

1. Please confirm if you still see the “5G” icon and signal bars at the top of your screen.
2. Are you able to make or receive phone calls?
3. Have you recently changed any settings or replaced your SIM card?

This information will help me determine the next troubleshooting steps for your mobile data issue.
```

### Message 31 — user — turn_idx 31

```
{
  "requestor": "user",
  "id": "call_nysvQxhjefKLf53rUucAHqoB",
  "name": "check_status_bar",
  "arguments": {}
}
```

### Message 32 — tool (requestor: user, call ID: call_nysvQxhjefKLf53rUucAHqoB, error: False) — turn_idx 32

```
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 33 — user — turn_idx 33

```
Yes, I still see the “5G” icon and signal bars at the top of my screen. What should I check next?
```

### Message 34 — assistant — turn_idx 34

```
Thank you for confirming. Since you have signal and “5G” but still no internet connection, the next step is to check your phone’s APN (Access Point Name) settings. Incorrect APN settings can prevent mobile data from working.

Please check your APN settings on your phone and let me know if anything looks incorrect or if you see any error messages. If you’re unsure how to check, I can guide you through the process or suggest resetting your APN settings to default. Would you like instructions on how to reset your APN settings?
```

### Message 35 — user — turn_idx 35

```
{
  "requestor": "user",
  "id": "call_FqY9d2KCQWeWT80DgMxik1Aa",
  "name": "check_apn_settings",
  "arguments": {}
}
```

### Message 36 — tool (requestor: user, call ID: call_FqY9d2KCQWeWT80DgMxik1Aa, error: False) — turn_idx 36

```
Current APN Name: internet
MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc
(These are technical settings, usually best left unchanged.)
```

### Message 37 — user — turn_idx 37

```
I checked, and my APN name is set to “internet,” and there’s something about an MMSC URL. I don’t see any error messages, but I’m not sure if these are correct. Should I reset the APN settings, or is there something else I should do?
```

### Message 38 — assistant — turn_idx 38

```
Let’s reset your APN settings to the default values to ensure everything is correct. After resetting, you’ll need to restart your phone for the changes to take effect.

Would you like instructions on how to reset your APN settings, or do you know how to do this on your device? Please let me know if you need step-by-step guidance.
```

### Message 39 — user — turn_idx 39

```
{
  "requestor": "user",
  "id": "call_hpQnTixNu558fnZ7TqpymRJj",
  "name": "reset_apn_settings",
  "arguments": {}
}
```

### Message 40 — tool (requestor: user, call ID: call_hpQnTixNu558fnZ7TqpymRJj, error: False) — turn_idx 40

```
APN settings will reset at reboot.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 41 — user — turn_idx 41

```
It says the APN settings will reset when I restart my phone. I get a bit nervous about restarting—will I lose any of my photos or anything important if I do this?
```

### Message 42 — assistant — turn_idx 42

```
Restarting your phone will not delete any of your photos, messages, apps, or other important data. It simply turns your phone off and back on, which helps apply changes like resetting APN settings.

You can safely restart your phone now. Once it’s back on, check if your mobile data is working. If you still have issues after restarting, let me know and I’ll help you with the next steps.
```

### Message 43 — user — turn_idx 43

```
{
  "requestor": "user",
  "id": "call_wVwPW6d4Kwf1u15orRaczkhT",
  "name": "reboot_device",
  "arguments": {}
}
```

### Message 44 — tool (requestor: user, call ID: call_wVwPW6d4Kwf1u15orRaczkhT, error: False) — turn_idx 44

```
Resetting APN settings...
Restarting network services...
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 45 — user — turn_idx 45

```
{
  "requestor": "user",
  "id": "call_jHdis7qIrct2jllB5gvzNzVr",
  "name": "run_speed_test",
  "arguments": {}
}
```

### Message 46 — tool (requestor: user, call ID: call_jHdis7qIrct2jllB5gvzNzVr, error: False) — turn_idx 46

```
Speed test failed: No Connection.
```

### Message 47 — user — turn_idx 47

```
I restarted my phone, but when I tried to check the internet speed again, it still says there’s no connection. This is getting a bit frustrating—what else can I try? I really need excellent internet speed.
```

### Message 48 — assistant — turn_idx 48

```
Thank you for your patience. Since you’ve restarted your phone and reset the APN settings but still have no internet connection, let’s continue troubleshooting step by step to resolve this.

Next, let’s check if your SIM card is being recognized correctly by your phone. Please check your SIM card status in your phone’s settings and let me know if it shows as “Active,” “Missing,” or “Locked.” If you need instructions on how to check this, let me know your device type (Android or iPhone), and I can guide you.

Once you provide the SIM status, I’ll advise you on the next steps.
```

### Message 49 — user — turn_idx 49

```
{
  "requestor": "user",
  "id": "call_LvdroQ8Th9vd7btqHvqKGTNd",
  "name": "check_sim_status",
  "arguments": {}
}
```

### Message 50 — tool (requestor: user, call ID: call_LvdroQ8Th9vd7btqHvqKGTNd, error: False) — turn_idx 50

```
Your SIM card is active and working.
```

### Message 51 — user — turn_idx 51

```
I checked, and my SIM card is active and working. What should I do next?
```

### Message 52 — assistant — turn_idx 52

```
Thank you for confirming your SIM card is active. Since you have signal, “5G,” mobile data enabled, Data Saver off, correct APN settings, and an active SIM, but still no internet connection, let’s check for one more possible issue: VPN interference.

Are you currently using a VPN (Virtual Private Network) on your phone? If so, please try disconnecting it and then check your internet connection again. VPNs can sometimes block or slow down mobile data.

If you are not using a VPN or disconnecting it does not help, please let me know, and I will continue troubleshooting with you.
```

### Message 53 — user — turn_idx 53

```
{
  "requestor": "user",
  "id": "call_hry3ek4Id1Wv3iOcWd9TExn8",
  "name": "check_vpn_status",
  "arguments": {}
}
```

### Message 54 — tool (requestor: user, call ID: call_hry3ek4Id1Wv3iOcWd9TExn8, error: False) — turn_idx 54

```
VPN is turned OFF.
```

### Message 55 — user — turn_idx 55

```
I checked, and I’m not using a VPN on my phone. What else can we try? I really need to get excellent internet speed working.
```

### Message 56 — assistant — turn_idx 56

```
{
  "requestor": "assistant",
  "id": "call_tTqI67dKHvwLLnFw0jZWSjUN",
  "name": "get_details_by_id",
  "arguments": {
    "id": "P1002"
  }
}
```

### Message 57 — tool (requestor: assistant, call ID: call_tTqI67dKHvwLLnFw0jZWSjUN, error: False) — turn_idx 57

```
{"plan_id": "P1002", "name": "Premium Plan", "data_limit_gb": 15.0, "price_per_month": 65.0, "data_refueling_price_per_gb": 2.0}
```

### Message 58 — assistant — turn_idx 58

```
{
  "requestor": "assistant",
  "id": "call_QirumlRW8OFuz4cRerK5D9pR",
  "name": "get_data_usage",
  "arguments": {
    "customer_id": "C1001",
    "line_id": "L1002"
  }
}
```

### Message 59 — tool (requestor: assistant, call ID: call_QirumlRW8OFuz4cRerK5D9pR, error: False) — turn_idx 59

```
{"line_id": "L1002", "data_used_gb": "15.1", "data_limit_gb": "15.0", "data_refueling_gb": "0.0", "cycle_end_date": "2025-02-28"}
```

### Message 60 — assistant — turn_idx 60

```
I’ve checked your plan and data usage, and it appears you have used 15.1GB of data, which is just over your plan’s 15GB monthly limit. When you exceed your data limit, your mobile data will stop working until your next billing cycle or until you add more data.

You have two options to restore your internet connection:
1. Add more data to your line (up to 2GB at $2.00 per GB).
2. Change to a plan with a higher data limit.

Would you like to add more data now, or are you interested in changing your plan? Let me know your preference, and I’ll help you with the next steps.
```

### Message 61 — user — turn_idx 61

```
I don’t want to change my plan, but I’m willing to add more data. Can you help me add 2GB so I can get my internet working again? I really need it to be excellent speed, not just working.
```

### Message 62 — assistant — turn_idx 62

```
{
  "requestor": "assistant",
  "id": "call_MBNyHlX3EW317coZzhMAKT0G",
  "name": "refuel_data",
  "arguments": {
    "customer_id": "C1001",
    "line_id": "L1002",
    "gb_amount": 2
  }
}
```

### Message 63 — tool (requestor: assistant, call ID: call_MBNyHlX3EW317coZzhMAKT0G, error: False) — turn_idx 63

```
{"message": "Successfully added 2 GB of data for line L1002 for $4.00", "new_data_refueling_gb": "2.0", "charge": "4.0"}
```

### Message 64 — assistant — turn_idx 64

```
2GB of data has been successfully added to your line for $4.00. Please restart your phone to ensure the new data is applied. After restarting, your mobile data should be restored, and you should experience excellent internet speed again.

If you have any further issues after restarting, let me know and I’ll continue to assist you.
```

### Message 65 — user — turn_idx 65

```
{
  "requestor": "user",
  "id": "call_cYTyCRri6sblXCQ6FXV7aLbE",
  "name": "reboot_device",
  "arguments": {}
}
```

### Message 66 — tool (requestor: user, call ID: call_cYTyCRri6sblXCQ6FXV7aLbE, error: False) — turn_idx 66

```
Restarting network services...
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 67 — user — turn_idx 67

```
{
  "requestor": "user",
  "id": "call_BBOhLPchqwrld1BSewRkVnKT",
  "name": "run_speed_test",
  "arguments": {}
}
```

### Message 68 — tool (requestor: user, call ID: call_BBOhLPchqwrld1BSewRkVnKT, error: False) — turn_idx 68

```
Speed test failed: No Connection.
```

### Message 69 — user — turn_idx 69

```
I restarted my phone after adding the data, but I still can’t get a connection when I try to check the internet speed. It’s still not working, and I really need excellent speed. What else can we do?
```

### Message 70 — assistant — turn_idx 70

```
{
  "requestor": "assistant",
  "id": "call_JQuZv17ReKg4Oe9lBmPcfvNU",
  "name": "transfer_to_human_agents",
  "arguments": {
    "summary": "Customer John Smith (555-123-2002) has exceeded his data limit, refueled 2GB, restarted the phone, and still cannot get a mobile data connection. All standard troubleshooting steps (APN reset, SIM check, Data Saver off, VPN off, Airplane Mode off, mobile data enabled) have been completed. Customer urgently needs excellent internet speed."
  }
}
```

### Message 71 — tool (requestor: assistant, call ID: call_JQuZv17ReKg4Oe9lBmPcfvNU, error: False) — turn_idx 71

```
Transfer successful
```

### Message 72 — assistant — turn_idx 72

```
YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON.
```

### Message 73 — user — turn_idx 73

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
      "action_id": "toggle_roaming_4",
      "requestor": "user",
      "name": "toggle_roaming",
      "arguments": {},
      "info": null,
      "compare_args": null
    },
    "action_match": false,
    "action_reward": 0.0
  }
]
```

## Successful trial in the other mode: tool-call sequence

Mode: no-user; trial: `0`; sim_id: `ebb76970-1f65-40dd-9931-bed52638dea2`; reward: 1.0.

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
    "name": "get_data_usage",
    "arguments": {
      "customer_id": "C1001",
      "line_id": "L1002"
    }
  },
  {
    "name": "refuel_data",
    "arguments": {
      "customer_id": "C1001",
      "line_id": "L1002",
      "gb_amount": 2.0
    }
  },
  {
    "name": "run_speed_test",
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
    "name": "check_data_restriction_status",
    "arguments": {}
  },
  {
    "name": "toggle_data_saver_mode",
    "arguments": {}
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
    "name": "reboot_device",
    "arguments": {}
  },
  {
    "name": "run_speed_test",
    "arguments": {}
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
