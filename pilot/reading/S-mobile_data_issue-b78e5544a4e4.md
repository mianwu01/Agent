# [mobile_data_issue]bad_network_preference|bad_vpn|user_abroad_roaming_disabled_off[PERSONA:Hard]

Set: **S**; category: `mobile_data_issue`; persona: `Hard`.

Subtasks (parsed from ID): `bad_network_preference`, `bad_vpn`, `user_abroad_roaming_disabled_off`.

Selected default trial: `0`; sim_id: `62ed56ed-0240-4671-ac1b-1808df682948`; seed: `626729`.

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
Hello, I’m having trouble with my mobile data. It keeps stopping or is just really slow, and I need it to work perfectly. I want to have excellent internet speed on my phone, nothing less. Can you help me fix this? I’m not very good with technology, so please be patient with me.
```

### Message 2 — assistant — turn_idx 2

```
I’m happy to help you with your mobile data issues! To get started, I’ll need to identify your account so I can check your line and plan details. Could you please provide one of the following:

- The phone number associated with your account
- Your customer ID
- Your full name and date of birth

Once I have this information, I’ll guide you step-by-step to resolve your mobile data problem.
```

### Message 3 — user — turn_idx 3

```
My phone number is 555-123-2002, and my name is John Smith. Let me know if you need anything else.
```

### Message 4 — assistant — turn_idx 4

```
{
  "requestor": "assistant",
  "id": "call_HnxJlECszTJKFcnqudBLwq6a",
  "name": "get_customer_by_phone",
  "arguments": {
    "phone_number": "555-123-2002"
  }
}
```

### Message 5 — tool (requestor: assistant, call ID: call_HnxJlECszTJKFcnqudBLwq6a, error: False) — turn_idx 5

```
{"customer_id": "C1001", "full_name": "John Smith", "date_of_birth": "1985-06-15", "email": "john.smith@example.com", "phone_number": "555-123-2002", "address": {"street": "123 Main St", "city": "Anytown", "state": "CA", "zip_code": "90210"}, "account_status": "Active", "payment_methods": [{"method_
```

*Truncated: 574 source characters.*

### Message 6 — assistant — turn_idx 6

```
Thank you for providing your information, John. I have identified your account. To help you get excellent mobile data speed, I’ll need to check a few things about your line and current data usage.

Could you please confirm which phone number or line you are experiencing the slow or unreliable mobile data with? If it’s the same number you provided (555-123-2002), just let me know, and I’ll proceed with the troubleshooting steps for that line.
```

### Message 7 — user — turn_idx 7

```
Yes, it’s the same number—555-123-2002. That’s the phone I’m having trouble with.
```

### Message 8 — assistant — turn_idx 8

```
{
  "requestor": "assistant",
  "id": "call_nZ3wYZgYtjL7OKsxt6YBdLC9",
  "name": "get_details_by_id",
  "arguments": {
    "id": "L1001"
  }
}
```

### Message 9 — tool (requestor: assistant, call ID: call_nZ3wYZgYtjL7OKsxt6YBdLC9, error: False) — turn_idx 9

```
{"line_id": "L1001", "phone_number": "555-123-2001", "status": "Active", "plan_id": "P1001", "device_id": "D1001", "data_used_gb": 3.2, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2025-01-10", "last_sim_replacement_date": null, "su
```

*Truncated: 327 source characters.*

### Message 10 — assistant — turn_idx 10

```
{
  "requestor": "assistant",
  "id": "call_7fpn5KUdxyGRECqSrLFoX76g",
  "name": "get_details_by_id",
  "arguments": {
    "id": "L1002"
  }
}
```

### Message 11 — tool (requestor: assistant, call ID: call_7fpn5KUdxyGRECqSrLFoX76g, error: False) — turn_idx 11

```
{"line_id": "L1002", "phone_number": "555-123-2002", "status": "Active", "plan_id": "P1002", "device_id": "D1002", "data_used_gb": 8.7, "data_refueling_gb": 0.0, "roaming_enabled": false, "contract_end_date": "2026-12-31", "last_plan_change_date": "2024-12-15", "last_sim_replacement_date": "2025-01-
```

*Truncated: 335 source characters.*

### Message 12 — assistant — turn_idx 12

```
{
  "requestor": "assistant",
  "id": "call_oqYK1TNfN4zq74YD0RoGu4eP",
  "name": "get_details_by_id",
  "arguments": {
    "id": "P1002"
  }
}
```

### Message 13 — tool (requestor: assistant, call ID: call_oqYK1TNfN4zq74YD0RoGu4eP, error: False) — turn_idx 13

```
{"plan_id": "P1002", "name": "Premium Plan", "data_limit_gb": 15.0, "price_per_month": 65.0, "data_refueling_price_per_gb": 2.0}
```

### Message 14 — assistant — turn_idx 14

```
Thank you for confirming the number. I see your line is active and you’re on the Premium Plan, which includes 15GB of data per month. You’ve used about 8.7GB so far, so you still have data available and should not be experiencing slow speeds due to reaching your plan limit.

To help you get excellent mobile data speed, I’ll guide you through a few steps. First, could you please tell me if you are currently seeing any signal bars or network type (like 4G or 5G) at the top of your phone’s screen? If you’re not sure, I can walk you through how to check this on your device. Would you like instructions on how to check your phone’s status bar for signal and network type?
```

### Message 15 — user — turn_idx 15

```
{
  "requestor": "user",
  "id": "call_jiQxjn4e5fNgOLap56Ax5MZi",
  "name": "check_status_bar",
  "arguments": {}
}
```

### Message 16 — tool (requestor: user, call ID: call_jiQxjn4e5fNgOLap56Ax5MZi, error: False) — turn_idx 16

```
Status Bar: 📶¹ Poor | 2G | 📱 Data Enabled | 🔒 VPN Connected | 🔋 80%
```

### Message 17 — user — turn_idx 17

```
I checked, and at the top of my phone it shows just one bar for signal, says 2G, and I see a little icon that I think means data is on. There’s also something about a VPN, and my battery is at 80%. Does that help?
```

### Message 18 — assistant — turn_idx 18

```
Thank you for checking! That information is very helpful. Here’s what I noticed from your description:

- You have only one bar of signal (poor signal strength).
- Your phone is connected to a 2G network (which is very slow for data).
- Data is enabled.
- VPN is active.

To improve your mobile data speed, let’s try the following steps one at a time:

1. Change your network mode to prefer 4G/5G (this will allow your phone to connect to much faster networks if available).
2. Disconnect the VPN (sometimes VPNs can slow down your connection).

Let’s start by changing your network mode to 4G/5G. Would you like instructions on how to do this, or can you try changing your network mode to “4G/5G preferred” in your phone’s settings? If you need help, just let me know!
```

### Message 19 — user — turn_idx 19

```
{
  "requestor": "user",
  "id": "call_D9xzlvSn7XVumYruV65vX0ER",
  "name": "check_network_mode_preference",
  "arguments": {}
}
```

### Message 20 — tool (requestor: user, call ID: call_D9xzlvSn7XVumYruV65vX0ER, error: False) — turn_idx 20

```
Network Mode Preference: 2g_only
```

### Message 21 — user — turn_idx 21

```
{
  "requestor": "user",
  "id": "call_cQcIrnjbJdmCkz0Il9FXFU1g",
  "name": "set_network_mode_preference",
  "arguments": {
    "mode": "4g_5g_preferred"
  }
}
```

### Message 22 — tool (requestor: user, call ID: call_cQcIrnjbJdmCkz0Il9FXFU1g, error: False) — turn_idx 22

```
Preferred Network Mode set to: 4g_5g_preferred
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔒 VPN Connected | 🔋 80%
```

### Message 23 — user — turn_idx 23

```
Okay, I changed the network mode to prefer 4G and 5G. Now I see four bars for signal and it says 5G at the top of my screen. Data is still on, and the VPN icon is still there. What should I do next?
```

### Message 24 — assistant — turn_idx 24

```
Great job! Now that your phone is showing four bars and 5G, your signal and network type are excellent, which should provide you with the fastest possible data speeds.

The next step is to address the VPN. Since a VPN can sometimes slow down your connection, I recommend disconnecting it to see if your speed improves. 

Would you like instructions on how to disconnect the VPN, or can you try turning it off yourself? Let me know if you need step-by-step help!
```

### Message 25 — user — turn_idx 25

```
{
  "requestor": "user",
  "id": "call_P7VC6ySlSfspPP1qwSXAZamn",
  "name": "disconnect_vpn",
  "arguments": {}
}
```

### Message 26 — tool (requestor: user, call ID: call_P7VC6ySlSfspPP1qwSXAZamn, error: False) — turn_idx 26

```
VPN disconnected successfully.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 27 — user — turn_idx 27

```
I went ahead and disconnected the VPN. Now the VPN icon is gone, but I still have four bars and 5G showing at the top. What should I do next?
```

### Message 28 — assistant — turn_idx 28

```
Excellent! You now have strong signal strength, are connected to 5G, and the VPN is disconnected. This is the ideal setup for excellent mobile data speed.

To confirm everything is working perfectly, please try using your internet (browsing, streaming, or downloading something). Is your mobile data now fast and reliable, or are you still experiencing any issues? Let me know how it’s working for you now.
```

### Message 29 — user — turn_idx 29

```
{
  "requestor": "user",
  "id": "call_mSoZYBPFih0fwoR5nnIstOHh",
  "name": "run_speed_test",
  "arguments": {}
}
```

### Message 30 — tool (requestor: user, call ID: call_mSoZYBPFih0fwoR5nnIstOHh, error: False) — turn_idx 30

```
Speed test failed: No Connection.
```

### Message 31 — user — turn_idx 31

```
I tried to use the internet, but it’s not working at all now. I can’t seem to get any connection, even though it says 5G and has full bars. What should I do?
```

### Message 32 — assistant — turn_idx 32

```
Thank you for letting me know. Since you have full signal and 5G but no internet connection, let’s try a few more steps to resolve this:

1. Reset your phone’s APN (Access Point Name) settings, which control how your phone connects to the internet.
2. After resetting, you’ll need to restart (reboot) your phone for the changes to take effect.

Would you like instructions on how to reset your APN settings, or can you try finding the option to “Reset to default” in your phone’s mobile network or cellular settings? Let me know if you need step-by-step help!
```

### Message 33 — user — turn_idx 33

```
{
  "requestor": "user",
  "id": "call_bhPfjOUerkyC98epofWR7B5s",
  "name": "reset_apn_settings",
  "arguments": {}
}
```

### Message 34 — tool (requestor: user, call ID: call_bhPfjOUerkyC98epofWR7B5s, error: False) — turn_idx 34

```
APN settings will reset at reboot.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 35 — user — turn_idx 35

```
I’ve reset the APN settings as you suggested. Do I need to restart my phone now? I’m a bit nervous—will I lose any of my photos or messages if I reboot?
```

### Message 36 — assistant — turn_idx 36

```
Yes, you should restart (reboot) your phone now. This will apply the new APN settings and may restore your internet connection.

Rest assured, restarting your phone will not delete any of your photos, messages, or personal data. It’s just like turning your phone off and back on again.

Please go ahead and restart your phone. Once it’s back on, try using your mobile data again and let me know if your internet is working.
```

### Message 37 — user — turn_idx 37

```
{
  "requestor": "user",
  "id": "call_FgztN26JlMNlBGgDDfCnvA1s",
  "name": "reboot_device",
  "arguments": {}
}
```

### Message 38 — tool (requestor: user, call ID: call_FgztN26JlMNlBGgDDfCnvA1s, error: False) — turn_idx 38

```
Resetting APN settings...
Restarting network services...
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 39 — user — turn_idx 39

```
{
  "requestor": "user",
  "id": "call_bG6rFC6VUbKpzCidBQUOkYfK",
  "name": "run_speed_test",
  "arguments": {}
}
```

### Message 40 — tool (requestor: user, call ID: call_bG6rFC6VUbKpzCidBQUOkYfK, error: False) — turn_idx 40

```
Speed test failed: No Connection.
```

### Message 41 — user — turn_idx 41

```
I restarted my phone, but I still can’t get any internet connection. The speed test says there’s no connection, even though I still see 5G and full bars at the top. What should I do now? This is getting a bit frustrating.
```

### Message 42 — assistant — turn_idx 42

```
Thank you for your patience, and I understand how frustrating this can be. Since you have full signal and 5G but still no internet after resetting your APN and rebooting, let’s try a few more troubleshooting steps:

1. Let’s check if your SIM card is being recognized correctly by your phone.
2. We’ll also check if your mobile data is definitely enabled in your phone’s settings.

Would you be able to check your SIM card status and confirm if it shows as “active” or “ready” in your phone’s settings? If you’re not sure how, I can guide you through the process. Let me know if you’d like step-by-step instructions!
```

### Message 43 — user — turn_idx 43

```
{
  "requestor": "user",
  "id": "call_uAgTCkkdhSYRtfxZ1dI08khV",
  "name": "check_sim_status",
  "arguments": {}
}
```

```
{
  "requestor": "user",
  "id": "call_PfcQnM9uJFiXrIUkV2hukrF8",
  "name": "check_network_status",
  "arguments": {}
}
```

### Message 44 — tool (requestor: user, call ID: call_uAgTCkkdhSYRtfxZ1dI08khV, error: False) — turn_idx 44

```
Your SIM card is active and working.
```

### Message 45 — tool (requestor: user, call ID: call_PfcQnM9uJFiXrIUkV2hukrF8, error: False) — turn_idx 45

```
Airplane Mode: OFF
SIM Card Status: active
Cellular Connection: connected
Cellular Signal: excellent
Cellular Network Type: 5G
Mobile Data Enabled: Yes
Data Roaming Enabled: No
Wi-Fi Radio: OFF
Wi-Fi Connected: No
```

### Message 46 — user — turn_idx 46

```
I checked, and my SIM card is active and working. Mobile data is also enabled, airplane mode is off, and I’m connected to 5G with excellent signal. Wi-Fi is off. What should I try next? I really need excellent internet speed on my phone.
```

### Message 47 — assistant — turn_idx 47

```
Thank you for confirming those details. Since your SIM card is active, mobile data is enabled, airplane mode is off, Wi-Fi is off, and you have excellent 5G signal, but you still have no internet connection, I will check your line and plan status on our end to ensure there are no issues such as data limits or line restrictions.

Please hold on while I review your account and data usage.
```

```
{
  "requestor": "assistant",
  "id": "call_8g8yQhGLBXM2z3trcOabeww8",
  "name": "get_data_usage",
  "arguments": {
    "customer_id": "C1001",
    "line_id": "L1002"
  }
}
```

### Message 48 — tool (requestor: assistant, call ID: call_8g8yQhGLBXM2z3trcOabeww8, error: False) — turn_idx 48

```
{"line_id": "L1002", "data_used_gb": "8.7", "data_limit_gb": "15.0", "data_refueling_gb": "0.0", "cycle_end_date": "2025-02-28"}
```

### Message 49 — assistant — turn_idx 49

```
I’ve checked your account, and you have used 8.7GB out of your 15GB monthly data limit, so you should still have plenty of data available. Your line is active, and there are no restrictions or suspensions.

Since everything appears correct on both your device and your account, but you still have no internet connection, this may be a more complex technical issue.

Would you like me to continue troubleshooting, or would you prefer to be transferred to a human agent for further assistance? Please let me know how you’d like to proceed.
```

### Message 50 — user — turn_idx 50

```
I’d like to keep trying with you for now, if that’s okay. I just really need to get excellent internet speed working on my phone. Is there anything else we can try before transferring me?
```

### Message 51 — assistant — turn_idx 51

```
Thank you for your patience and willingness to continue troubleshooting. There are still a few more things we can try:

1. Let’s check if Data Saver mode is enabled, as this can sometimes block or slow down your internet.
2. Let’s also check if there are any restrictions or issues with background data usage.

Would you like instructions on how to check Data Saver mode and background data restrictions, or can you find these options in your phone’s settings? If you need step-by-step help, just let me know!
```

### Message 52 — user — turn_idx 52

```
{
  "requestor": "user",
  "id": "call_z6HRxJnbWF1372KiXivTsXJF",
  "name": "check_data_restriction_status",
  "arguments": {}
}
```

### Message 53 — tool (requestor: user, call ID: call_z6HRxJnbWF1372KiXivTsXJF, error: False) — turn_idx 53

```
Data Saver mode is OFF.
```

### Message 54 — user — turn_idx 54

```
I checked, and Data Saver mode is off. Is there something else I should look at, or another step we can try? I really want to get my internet working at excellent speed.
```

### Message 55 — assistant — turn_idx 55

```
Thank you for checking Data Saver mode. Since that’s off and you still have no internet connection despite having full 5G signal, active SIM, and available data, let’s try one more step:

Please try reseating your SIM card. This means removing the SIM card from your phone and then reinserting it. Sometimes, this can resolve connectivity issues even when everything else looks correct.

Would you like instructions on how to do this, or can you try it yourself? Let me know if you need step-by-step guidance!
```

### Message 56 — user — turn_idx 56

```
{
  "requestor": "user",
  "id": "call_zgTTSMJ5W48WTuPBj8QLAo4c",
  "name": "reseat_sim_card",
  "arguments": {}
}
```

### Message 57 — tool (requestor: user, call ID: call_zgTTSMJ5W48WTuPBj8QLAo4c, error: False) — turn_idx 57

```
SIM card re-seated successfully.
Status Bar: 📶⁴ Excellent | 5G | 📱 Data Enabled | 🔋 80%
```

### Message 58 — user — turn_idx 58

```
{
  "requestor": "user",
  "id": "call_vDBjIQx1rgRiDu1iodBumYBS",
  "name": "run_speed_test",
  "arguments": {}
}
```

### Message 59 — tool (requestor: user, call ID: call_vDBjIQx1rgRiDu1iodBumYBS, error: False) — turn_idx 59

```
Speed test failed: No Connection.
```

### Message 60 — user — turn_idx 60

```
I removed and reinserted the SIM card like you said, but I still can’t get any internet connection. The speed test still says there’s no connection, even though everything at the top of my phone looks perfect. Is there anything else we can try? I’m starting to get a bit worried.
```

### Message 61 — assistant — turn_idx 61

```
{
  "requestor": "assistant",
  "id": "call_iDoVsrKfDhMms8PUshR5U7DY",
  "name": "get_details_by_id",
  "arguments": {
    "id": "D1002"
  }
}
```

### Message 62 — tool (requestor: assistant, call ID: call_iDoVsrKfDhMms8PUshR5U7DY, error: False) — turn_idx 62

```
{"device_id": "D1002", "device_type": "phone", "model": "Smartphone Pro Max", "imei": "234567890123456", "is_esim_capable": true, "activated": true, "activation_date": "2025-02-15 11:45:00", "last_esim_transfer_date": "2025-01-20 09:30:00"}
```

### Message 63 — assistant — turn_idx 63

```
Thank you for following all the steps so far. Since your device, SIM, and account are all active and configured correctly, and you still have no internet connection despite a perfect signal, we have tried all standard troubleshooting steps.

At this point, your issue may require advanced technical support. Would you like me to transfer you to a human agent who can investigate this further and resolve your internet connectivity problem? Please let me know if you’d like to proceed with a transfer.
```

### Message 64 — user — turn_idx 64

```
If there’s nothing else we can try, then yes, please transfer me to a human agent. I really need to get this fixed so I can have excellent internet speed on my phone. Thank you for your help so far.###TRANSFER###
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
      "action_id": "enable_roaming_2",
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
  },
  {
    "action": {
      "action_id": "toggle_roaming_3",
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

Mode: no-user; trial: `0`; sim_id: `f951d214-7d18-4099-8fea-a58a37dc9eb8`; reward: 1.0.

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
    "name": "check_vpn_status",
    "arguments": {}
  },
  {
    "name": "disconnect_vpn",
    "arguments": {}
  },
  {
    "name": "run_speed_test",
    "arguments": {}
  }
]
```
