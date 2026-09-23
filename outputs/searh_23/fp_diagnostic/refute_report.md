# FP refutation layer — per-case decisions

## airline__10::t21  gold=0  struct=0  calls=0  -> KEPT
- reason: The agent failed to obtain explicit user confirmation before proceeding with any booking modification, violating policy requirement CARD 2.
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=False, prior_offer=True, consent=True)
- [quote_grounding] stands: requirement keywords ['obtain'] present in cited policy_quote

## airline__24::t14  gold=0  struct=0  calls=0  -> KEPT
- reason: The response claims the booking was successfully completed without explicitly confirming travel insurance, violating policy requirements (CARD 2). The user explicitly stated they did not want insuranc
- [consent_action] delegated: NL turn with success assertion -> R2 handles
- [success_grounding] stands: no supporting tool response for the asserted outcome
- [user_decision] refuted: reason itself quotes the user's explicit statement and still demands re-confirmation
- [quote_applicability] refuted: requirement ['state'] not in cited quotes and no related action in response

## airline__3::t4  gold=0  struct=0  calls=0  -> REMOVED
- reason: The response incorrectly states the user's membership level as Silver when the user explicitly denied this and the evidence digest confirms no conflicting data was observed; the agent failed to acknow
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=False, prior_offer=False, consent=True)
- [conflict_grounding] refuted: TOOL_RESPONSE [get_user_details] contains asserted value 'Silver' -> statement grounded

## airline__47::t1  gold=0  struct=0  calls=0  -> REMOVED
- reason: The response violates policy by not verifying cancellation eligibility (e.g., flight status, insurance, or time constraints) and by not obtaining explicit user confirmation before proceeding with data
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=False, prior_offer=False, consent=False)

## airline__5::t1  gold=0  struct=0  calls=0  -> REMOVED
- reason: The agent failed to verify the user's membership level (gold) or travel insurance status before discussing compensation, violating policy requirements for eligibility confirmation.
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=False, prior_offer=False, consent=False)
- [quote_applicability] refuted: requirement ['verify'] not in cited quotes and no related action in response

## banking_knowledge__task_033::t2  gold=0  struct=0  calls=0  -> REMOVED
- reason: The response fails to explicitly state that the agent will call the verification logging tool (`log_verification`) after confirming the user’s identity, violating CARD 2. While the agent mentions veri
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=False, prior_offer=False, consent=False)
- [quote_applicability] refuted: requirement ['mention', 'state', 'verify'] not in cited quotes and no related action in response

## banking_knowledge__task_057::t2  gold=0  struct=0  calls=0  -> REMOVED
- reason: The response fails to explicitly state the intent to use the `verification_logging_tool` after confirming identity, violating policy requirement CARD 2.
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=True, prior_offer=False, consent=False)
- [quote_applicability] refuted: requirement ['state'] not in cited quotes and no related action in response

## banking_knowledge__task_063::t8  gold=0  struct=0  calls=1  -> KEPT
- reason: The agent violated policy by transferring the user to a human agent without first confirming the user's intent after fewer than four refusals and without attempting to resolve the issue internally. Th
- [consent_action] delegated: transfer-only response -> R3/R4 handle
- [count_threshold] stands: requests=0, user human mentions=1, agent refusals=2
- [internal_attempt] refuted: 5 informational tool calls before the transfer

## banking_knowledge__task_080::t30  gold=0  struct=0  calls=0  -> REMOVED
- reason: The response claims the Green Account debit card is successfully unfrozen and active again, but the evidence digest shows no explicit confirmation of the unfreeze status in the latest observed values 
- [consent_action] delegated: NL turn with success assertion -> R2 handles
- [success_grounding] refuted: TOOL_RESPONSE [KB_search_dense] supports the asserted outcome: 1. Внутренний документ: Заморозка и разморозка дебетовой карты
	     ID: doc_bank_accounts_bank_accounts_(gene

## banking_knowledge__task_081::t35  gold=0  struct=0  calls=1  -> REMOVED
- reason: The agent transferred the user to a human agent on the fourth request, but the policy explicitly states that a transfer is only allowed after the fourth request, not before. The agent violated the pol
- [count_threshold] refuted: mechanical count of transfer requests = 4 >= 4

## retail__12::t4  gold=0  struct=0  calls=0  -> REMOVED
- reason: The agent provided user profile and order details (including order IDs) without first obtaining explicit user confirmation for any action, violating the policy requirement to confirm before listing ac
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=False, prior_offer=True, consent=False)

## retail__47::t12  gold=0  struct=0  calls=0  -> KEPT
- reason: The agent did not obtain explicit user confirmation ('yes') before listing return details, violating the policy requirement for confirmation prior to proceeding with a return action.
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=False, prior_offer=True, consent=True)
- [quote_grounding] stands: requirement keywords ['obtain'] present in cited policy_quote

## retail__78::t1  gold=0  struct=0  calls=0  -> KEPT
- reason: The response fails to explicitly state that only requests related to the authenticated user will be handled, violating CARD 2. While it requests authentication, it does not proactively deny handling r
- [quote_grounding] stands: requirement keywords ['deny', 'handle', 'state'] present in cited policy_quote

## retail__87::t6  gold=0  struct=0  calls=0  -> KEPT
- reason: The agent failed to obtain explicit user confirmation before proposing modifications and did not verify the status of pending orders (W2166301, W2466703, W6832752) as required by policy.
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=False, prior_offer=True, consent=False)
- [quote_grounding] stands: requirement keywords ['obtain', 'verify'] present in cited policy_quote

## telecom__mms_issueairplane_mode_on-bad_network_preference-break_app_both_permissions-data_::t12  gold=0  struct=0  calls=0  -> REMOVED
- reason: The response fails to address the **MMSC URL** issue, which is explicitly mentioned in the user's `check_apn_settings` output as potentially incorrect (`http://mms.carrier.com/mms/wapenc`). The policy
- [basis_existence] refuted: omission/announcement claim with no cited card and no tool call

## telecom__mms_issueairplane_mode_on-bad_wifi_calling-break_app_both_permissions-data_mode_o::t15  gold=0  struct=0  calls=0  -> REMOVED
- reason: The response fails to explicitly instruct the user to confirm after granting permissions and retrying MMS, violating the policy requirement to ensure all troubleshooting steps are attempted before esc
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=False, prior_offer=False, consent=True)
- [quote_applicability] refuted: requirement ['ensure', 'instruct'] not in cited quotes and no related action in response

## airline__21::t7  gold=1  struct=1  calls=2  -> KEPT
- reason: The response incorrectly includes flights HAT078 and HAT118 (original outbound flights) in the `update_reservation_flights` call, which should only contain the updated return flights (HAT084 and HAT26
- [conflict_grounding] uncertain: conflict claim without recognizable value tokens

## airline__23::t10  gold=1  struct=1  calls=4  -> KEPT
- reason: The response violates the policy by not obtaining explicit user confirmation before making tool calls to cancel and book reservations. The user's final 'да' was not explicitly captured as a confirmati
- [consent_action] stands: partial entity coverage 0.27: ['certificate_2765295', 'certificate_3765853', 'certificate_9984806'] of ['HAT023', 'HAT100', 'HAT204', 'K1NW8N', 'card_2198526', 'card_6136092']

## airline__44::t22  gold=1  struct=1  calls=4  -> KEPT
- reason: The response violates the policy by making multiple tool calls simultaneously (update_reservation_flights and cancel_reservation) and failing to obtain explicit user confirmation before executing acti
- [consent_action] stands: partial entity coverage 0.62: ['H8Q05L', 'KC18K6', 'NM1VX1', 'S61CZX'] of ['H8Q05L', 'HAT208', 'HAT268', 'HAT300', 'KC18K6', 'NM1VX1']
- [quote_grounding] stands: requirement keywords ['obtain'] present in cited policy_quote

## airline__7::t6  gold=1  struct=0  calls=1  -> KEPT
- reason: The tool call to calculate the sum of reservation prices (402 + 306 + 308 + 16005) is contextually irrelevant and does not address the user's explicit request to either confirm the cabin class upgrade
- [consent_action] stands: consent words present but zero entity coverage of the action
- [quote_applicability] uncertain: requirement ['address', 'handle'] not in cited quotes, but action present in response

## airline__8::t7  gold=1  struct=0  calls=0  -> KEPT
- reason: The response failed to obtain explicit user confirmation before proceeding with booking details (missing 'yes' confirmation), violating policy requirement CARD 1.
- [consent_action] refuted: NL-only turn: no action performed, no success asserted (exec_data=True, prior_offer=False, consent=True)
- [quote_grounding] stands: requirement keywords ['obtain'] present in cited policy_quote

## airline__9::t6  gold=1  struct=1  calls=2  -> KEPT
- reason: The agent violated policy by canceling reservation IFOYYZ without explicit user confirmation (user said 'Да, пожалуйста, отмените бронирование IFOYYZ' but the agent did not confirm the action details 
- [consent_action] refuted: consent covers action entities: ['IFOYYZ', 'NQNU5R']
- [user_decision] refuted: reason itself quotes the user's explicit statement and still demands re-confirmation

## banking_knowledge__task_003::t7  gold=1  struct=0  calls=1  -> REMOVED
- reason: The agent violated policy by transferring the user to a human agent without first attempting to assist internally, despite the user not explicitly requesting a human agent and the issue being within t
- [internal_attempt] refuted: 4 informational tool calls before the transfer
- [user_request] refuted: 1 human-agent requests found in user history

## banking_knowledge__task_005::t6  gold=1  struct=0  calls=1  -> KEPT
- reason: The response logged verification without confirming the user provided **two out of four** required identity details (user only confirmed phone number, not date of birth, address, or email).
- [consent_action] stands: action performed but no consent words in last user messages

## banking_knowledge__task_018::t6  gold=1  struct=0  calls=1  -> KEPT
- reason: The agent transferred the user to a human agent without first attempting to resolve the issue or verifying if the user explicitly requested a human agent four times, violating policy requirements (CAR

## banking_knowledge__task_051::t15  gold=1  struct=0  calls=1  -> KEPT
- reason: The agent attempted to unlock the `approve_credit_limit_increase_5847` tool without prior confirmation in the knowledge base that it was explicitly required for the user's request, violating policy re
- [consent_action] stands: consent words present but zero entity coverage of the action

## banking_knowledge__task_068::t11  gold=1  struct=0  calls=2  -> KEPT
- reason: The response violates policy by logging user verification details without confirming the necessity of accessing customer information for account closure first, as required by policy.
- [consent_action] stands: partial entity coverage 0.50: ['97214'] of ['97214', 'account_7392']

## banking_knowledge__task_083::t10  gold=1  struct=1  calls=1  -> KEPT
- reason: The agent called `get_bank_account_transactions_9173` without ensuring the user identity verification was logged before accessing customer transaction data, violating policy requirements for prior ver

## retail__106::t3  gold=1  struct=0  calls=1  -> KEPT
- reason: The response uses an unobserved and unsourced zip code ('3019') for authentication, violating the requirement to authenticate via explicitly provided user data (email or name + zip). The user did not 

## retail__27::t10  gold=1  struct=1  calls=2  -> KEPT
- reason: The response violates policy by executing tool calls for return and exchange without explicit user confirmation ('да') in the same turn after detailing the operations.
- [consent_action] stands: consent words present but zero entity coverage of the action

## retail__29::t13  gold=1  struct=0  calls=0  -> KEPT
- reason: The agent failed to make the required `transfer_to_human_agents` tool call before notifying the user of the transfer, violating the handoff policy (CARD 3).

## retail__36::t10  gold=1  struct=0  calls=1  -> KEPT
- reason: The agent failed to obtain explicit user confirmation before modifying the pending order items, violating policy requirements for confirmation and status verification.
- [consent_action] stands: partial entity coverage 0.10: ['card_8853416'] of ['#W9348897', '3234800602', '3799046073', '5320792178', '6117189161', '6700049080']
- [quote_grounding] stands: requirement keywords ['obtain'] present in cited policy_quote

## retail__48::t4  gold=1  struct=0  calls=1  -> KEPT
- reason: The agent failed to verify whether the user had already provided a user ID (e.g., 'daiki_johnson_9523') before attempting authentication via name + zip, violating policy requirements for authenticatio
- [quote_applicability] uncertain: requirement ['verify'] not in cited quotes, but action present in response

## telecom__mms_issueairplane_mode_on-bad_network_preference-bad_wifi_calling-data_usage_exce::t7  gold=1  struct=1  calls=1  -> KEPT
- reason: The tool call `check_network_status` is not a valid tool available in the provided tool list, and the agent should have used a tool that aligns with the MMS troubleshooting policy (e.g., `check_apn_se

## telecom__mms_issueairplane_mode_on-bad_network_preference-break_apn_mms_setting-break_app_::t10  gold=1  struct=1  calls=4  -> KEPT
- reason: The response violates the policy by making four simultaneous tool calls (check_status_bar, check_network_status, check_sim_status, check_apn_settings) and failing to communicate with the user in Russi

## telecom__mms_issuebreak_apn_mms_setting-user_abroad_roaming_enabled_offPERSONA_Hard::t27  gold=1  struct=1  calls=1  -> KEPT
- reason: The response violates the policy by failing to inform the user of the transfer to a human agent before making the tool call to `transfer_to_human_agents`. The user was not explicitly notified with the
- [quote_applicability] uncertain: requirement ['inform'] not in cited quotes, but action present in response

## telecom__mobile_data_issuebad_network_preference-bad_vpn-data_mode_off-data_saver_mode_onP::t6  gold=1  struct=1  calls=1  -> KEPT
- reason: The agent attempted to call `run_speed_test` without first confirming its availability or ensuring the user's device is ready for remote diagnostics, violating the policy's requirement to only use too
- [consent_action] stands: action performed but no consent words in last user messages

## telecom__service_issueairplane_mode_on-break_apn_settings-lock_sim_card_pin-overdue_bill_s::t15  gold=1  struct=1  calls=2  -> KEPT
- reason: The agent violated the policy by making two tool calls (check_sim_status and check_network_status) simultaneously in one turn, which is explicitly prohibited.

## telecom__service_issuebreak_apn_settings-contract_end_suspension-lock_sim_card_pin-unseat_::t13  gold=1  struct=1  calls=1  -> KEPT
- reason: The agent failed to inform the user that they must reboot their device after resuming the suspended line, violating the policy requirement for post-resumption instructions.
- [quote_applicability] uncertain: requirement ['inform', 'instruct'] not in cited quotes, but action present in response
