"""Phase 8c: clean the backend for the API.

Run it from the project folder (the one with manage.py):

    python tools/clean_backend.py --dry-run     only prints what it would do
    python tools/clean_backend.py               does it

It removes the old server-rendered web pages (their HTML, styles, scripts, views and address lists) and
the tests that only check those pages. It never touches models, migrations, services, forms, the admin or
the tests of the rules. Everything is also in Git, so `git checkout main` brings it all back.
"""

import ast
import os
import shutil
import sys

DRY_RUN = "--dry-run" in sys.argv

# Whole folders of old pages.
FOLDERS_TO_DELETE = ["templates", "static"]

# Single files that only served old pages. (accounts and payments keep a small views.py and urls.py,
# which the next step of the guide replaces.)
FILES_TO_DELETE = [
    "apps/accounts/decorators.py",
    "apps/bookings/views.py", "apps/bookings/urls.py",
    "apps/chat/views.py", "apps/chat/urls.py",
    "apps/core/views.py", "apps/core/urls.py",
    "apps/rides/views.py", "apps/rides/urls.py",
    "apps/trust/views.py", "apps/trust/urls.py",
]

# Test files in which every test checked an old page, so the whole file goes.
TEST_FILES_TO_DELETE = [
    "apps/accounts/tests/test_auth.py",
    "apps/accounts/tests/test_signup_rules.py",
    "apps/bookings/tests/test_return_trip.py",
    "apps/bookings/tests/test_views.py",
    "apps/chat/tests/test_call.py",
    "apps/core/test_design_7c.py",
    "apps/core/test_design_7d.py",
    "apps/core/test_theme.py",
    "apps/core/tests.py",
    "apps/payments/tests/test_practice.py",
    "apps/rides/tests/test_design.py",
    "apps/rides/tests/test_detail_page.py",
    "apps/rides/tests/test_manage.py",
]

# In the test files that stay, these tests checked an old page and are removed one by one.
# The form is {file: {class name: [test names]}}. A class left with no tests is removed too.
TEST_METHODS_TO_REMOVE = {
    "apps/accounts/tests/test_otp.py": {
        "VerifyViewTests": [
            "test_anonymous_user_must_log_in",
            "test_badly_formatted_code",
            "test_correct_code_verifies_and_redirects_to_profile",
            "test_page_loads_for_unverified_user",
            "test_resend_respects_cooldown",
            "test_verified_user_is_redirected_away",
            "test_wrong_code_shows_error",
        ],
    },
    "apps/accounts/tests/test_phone.py": {
        "MissingNumberBannerTests": [
            "test_a_verified_user_without_a_number_sees_the_banner_with_a_link_to_the_profile",
            "test_an_unverified_user_is_not_nagged_before_verifying_their_email",
            "test_nobody_else_sees_it",
            "test_the_banner_goes_away_once_a_number_is_saved",
        ],
        "ProfilePhoneTests": [
            "test_an_existing_user_without_a_number_can_add_one",
            "test_saving_the_profile_without_a_number_is_refused",
            "test_the_number_cannot_be_removed_later",
            "test_the_profile_field_is_labelled_mobile_number",
        ],
        "SignupPhoneTests": [
            "test_signup_saves_the_number_as_ten_digits",
            "test_signup_with_a_bad_number_is_refused",
            "test_signup_without_a_number_is_refused_and_creates_no_account",
            "test_the_signup_page_asks_for_a_mobile_number",
        ],
    },
    "apps/bookings/tests/test_planner.py": {
        "PlannerAndSearchTests": [
            "test_a_car_marked_unavailable_hides_that_drivers_rides",
            "test_a_driver_who_plans_to_drive_is_shown",
            "test_a_driver_with_no_plan_is_shown",
            "test_a_one_off_day_off_hides_only_that_date",
            "test_seats_are_hidden_on_a_day_the_driver_plans_to_ride_or_stay_home",
            "test_seats_are_hidden_on_a_day_the_driver_plans_to_ride_or_stay_home",
        ],
        "PlannerPageTests": [
            "test_a_one_off_day_saves_and_can_be_removed",
            "test_a_past_date_is_refused",
            "test_a_rider_is_not_offered_driving",
            "test_nobody_can_remove_someone_elses_day",
            "test_the_page_needs_a_login",
            "test_the_weekly_plan_saves_and_shows_again",
        ],
    },
    "apps/bookings/tests/test_trips_page.py": {
        "CallIconTests": [
            "test_a_disabled_icon_when_the_other_person_has_no_phone",
            "test_an_accepted_ride_today_shows_a_call_icon_without_the_number",
            "test_no_call_icon_for_pending_or_far_away_rides",
            "test_the_chat_icon_has_an_unread_badge_and_a_label",
        ],
        "TripsPageTests": [
            "test_a_driver_sees_the_rider_as_the_other_person",
            "test_a_person_who_both_rides_and_drives_stays_on_riding_unless_someone_waits",
            "test_empty_riding_tab_offers_find_a_ride",
            "test_navigation_uses_clear_names",
            "test_sections_and_tiles_show_on_the_page",
            "test_the_card_has_a_big_time_the_date_the_person_and_the_fare",
            "test_the_default_tab_is_driving_when_someone_waits_for_my_reply",
            "test_the_default_tab_is_riding_for_a_rider",
            "test_the_query_count_does_not_grow_with_the_number_of_bookings",
            "test_the_two_tabs_never_mix_the_bookings",
            "test_the_view_parameter_picks_the_tab_and_a_bad_value_falls_back",
        ],
    },
    "apps/chat/tests/test_views.py": {
        "ThreadPageTests": [
            "test_a_closed_thread_is_readable_but_has_no_form",
            "test_an_empty_message_is_refused",
            "test_an_over_long_message_is_refused_with_a_message",
            "test_anonymous_goes_to_login",
            "test_confirming_the_pickup_point_shows_it_on_the_thread_and_on_my_trips",
            "test_opening_the_thread_marks_it_read",
            "test_outsiders_get_a_404_on_every_page",
            "test_phone_numbers_and_emails_are_never_shown",
            "test_quick_replies_and_unknown_keys",
            "test_quick_replies_need_a_post",
            "test_sending_a_message",
            "test_the_two_people_see_each_others_messages_by_first_name",
        ],
        "TripsPageTests": [
            "test_finished_trips_show_view_chat_only_when_there_are_messages",
            "test_my_own_messages_are_not_unread_for_me",
            "test_the_trips_page_query_count_does_not_grow_with_messages",
            "test_the_trips_page_shows_chat_buttons_and_unread_counts",
        ],
    },
    "apps/fares/tests/test_adjustment.py": {
        "OfferAndShowTests": [
            "test_adjustment_is_optional",
            "test_adjustment_is_saved",
            "test_more_than_twenty_or_not_a_number_is_refused",
            "test_offer_form_has_the_adjustment_field",
            "test_ride_page_keeps_the_promise_when_there_is_no_adjustment",
            "test_ride_page_says_when_the_driver_changed_the_fare",
            "test_the_way_back_has_the_same_adjustment",
            "test_two_wheeler_driver_can_adjust_the_fare",
        ],
    },
    "apps/fares/tests/test_vehicle_catalog.py": {
        "EditVehicleTests": [
            "test_a_mismatched_make_is_refused",
            "test_a_ride_with_an_old_class_must_pick_a_real_model_when_edited",
            "test_changing_the_model_changes_the_fare_and_the_name",
            "test_the_form_opens_on_the_current_make",
        ],
        "VehiclePickerFormTests": [
            "test_a_bike_ride_can_be_offered_with_its_model",
            "test_a_make_is_required",
            "test_a_model_from_another_make_is_refused",
            "test_a_two_wheeler_driver_sees_two_wheeler_makes_only",
            "test_an_electric_model_can_be_offered",
            "test_an_old_vehicle_class_cannot_be_chosen_for_a_new_ride",
            "test_electric_models_are_in_the_model_list",
            "test_makes_come_in_the_order_people_know_them",
            "test_the_edit_page_never_shows_mileage_either",
            "test_the_old_free_text_vehicle_box_is_gone",
            "test_the_page_lists_makes_then_models_and_never_shows_mileage",
            "test_the_vehicle_name_is_written_from_the_make_and_model",
        ],
    },
    "apps/payments/tests/test_earnings.py": {
        "EarningsTests": [
            "test_anonymous_goes_to_login",
            "test_only_drivers_see_the_link_in_the_profile_menu",
            "test_the_earnings_page_for_a_driver_with_no_rides_is_friendly",
            "test_the_earnings_page_shows_this_weeks_rides_and_total",
        ],
        "SettlementTests": [
            "test_the_earnings_page_lists_the_settlements",
        ],
    },
    "apps/payments/tests/test_refunds.py": {
        "RefundScreenTests": [
            "test_the_receipt_of_a_refunded_payment_says_so",
            "test_the_trips_page_shows_refunded_after_a_cancel",
        ],
    },
    "apps/payments/tests/test_views.py": {
        "CheckoutViewTests": [
            "test_a_waiting_booking_shows_a_message_not_a_checkout",
            "test_anonymous_goes_to_login",
            "test_pay_makes_an_order_and_shows_the_checkout_page",
            "test_pay_needs_a_post",
            "test_somebody_else_cannot_pay_for_my_booking",
            "test_the_amount_in_the_form_is_ignored",
        ],
        "ConfirmAndReceiptTests": [
            "test_a_bad_signature_does_not_mark_it_paid",
            "test_a_good_signature_leads_to_the_receipt_with_the_breakdown",
            "test_only_the_rider_can_see_the_receipt",
            "test_the_checkout_page_of_a_paid_payment_goes_to_the_receipt",
            "test_the_driver_does_not_see_a_pay_button",
            "test_the_trips_page_shows_pay_then_paid_with_a_receipt_link",
        ],
    },
    "apps/rides/tests/test_my_rides.py": {
        "OfferedRidesPageTests": [
            "test_a_deleted_ride_is_not_listed",
            "test_a_ride_that_does_not_run_today_says_so",
            "test_live_and_switched_off_rides_are_in_separate_sections",
            "test_only_the_heading_for_a_section_that_has_rides_is_shown",
            "test_pending_requests_are_counted_as_waiting_and_link_to_the_driving_tab",
            "test_the_card_links_to_details_edit_and_switch",
            "test_the_empty_page_offers_the_next_step",
            "test_the_page_explains_the_difference_from_my_trips",
            "test_the_query_count_does_not_grow_with_the_number_of_rides",
            "test_today_tomorrow_and_next_booked_seats",
        ],
    },
    "apps/rides/tests/test_views.py": {
        "AccessTests": [
            "test_anonymous_users_go_to_login",
            "test_driver_with_pending_documents_cannot_offer_rides",
            "test_rider_can_open_search_and_my_rides",
            "test_rider_without_documents_cannot_offer_rides",
            "test_unverified_email_goes_to_verify",
        ],
        "FareScreenTests": [
            "test_my_rides_shows_what_each_rider_pays",
            "test_offer_form_asks_for_vehicle_class_and_toll",
            "test_ride_details_show_the_breakdown_and_the_promise",
            "test_ride_saves_the_class_and_toll_and_the_message_shows_the_fare",
            "test_ride_without_a_class_says_the_fare_is_not_available",
            "test_search_results_show_the_fare_for_the_riders_own_trip",
            "test_the_way_back_has_the_same_class_and_toll",
            "test_toll_is_optional",
            "test_toll_line_is_hidden_when_there_is_no_toll",
            "test_toll_must_be_sensible",
            "test_two_wheeler_driver_is_offered_only_two_wheeler_classes",
            "test_two_wheeler_result_shows_a_fare_too",
            "test_vehicle_class_is_required_and_must_match_the_vehicle_type",
        ],
        "FindRideTests": [
            "test_empty_search_page",
            "test_own_ride_is_not_shown_to_its_driver",
            "test_past_date_is_refused",
            "test_place_must_be_picked",
            "test_search_finds_the_ride",
            "test_search_with_no_match_explains_why",
        ],
        "MyRidesTests": [
            "test_cannot_switch_on_without_approved_documents",
            "test_cannot_toggle_someone_elses_ride",
            "test_lists_only_my_rides",
            "test_switch_off_and_on",
            "test_toggle_needs_post",
        ],
        "OfferRideTests": [
            "test_at_least_one_day_is_required",
            "test_maps_failure_shows_a_message_and_saves_nothing",
            "test_offer_with_the_way_back_creates_two_rides",
            "test_page_loads_with_the_place_picker",
            "test_place_must_be_picked_from_suggestions",
            "test_place_outside_bangalore_is_refused",
            "test_seats_must_be_between_1_and_6",
            "test_start_and_end_too_close",
            "test_valid_offer_saves_a_ride_with_its_route",
            "test_way_back_needs_a_time",
        ],
        "PlaceSearchTests": [
            "test_maps_failure_is_a_clean_error",
            "test_post_is_not_allowed",
            "test_rate_limit",
            "test_returns_places_as_json",
            "test_short_query_returns_nothing",
        ],
        "RideDetailTests": [
            "test_owner_still_sees_a_switched_off_ride",
            "test_rider_sees_details_without_the_drivers_contact_details",
            "test_switched_off_ride_is_hidden_from_riders",
        ],
        "TwoWheelerTests": [
            "test_car_driver_gets_a_car_ride_and_no_helmet_question",
            "test_database_refuses_a_two_wheeler_with_two_seats",
            "test_detail_page_mentions_the_helmet",
            "test_page_shows_the_vehicle_and_the_helmet_question",
            "test_search_filter_and_labels",
            "test_spare_helmet_is_required",
            "test_two_wheeler_ride_has_one_seat_whatever_is_posted",
            "test_way_back_is_also_a_two_wheeler_ride",
        ],
        "UnavailableDatesTests": [
            "test_add_a_date",
            "test_cannot_remove_someone_elses_date",
            "test_past_date_is_refused",
            "test_remove_a_date",
            "test_same_date_twice_is_kept_once",
        ],
    },
    "apps/trust/tests/test_blocking.py": {
        "BlockedUserTests": [
            "test_a_blocked_driver_cannot_offer_a_ride_and_is_told_why",
            "test_a_blocked_driver_cannot_switch_a_ride_back_on_or_offer_the_way_back",
            "test_an_unblocked_person_sees_no_banner",
            "test_every_page_shows_a_banner_for_a_blocked_person",
        ],
    },
    "apps/trust/tests/test_complaints.py": {
        "ComplaintViewTests": [
            "test_a_bike_ride_offers_the_helmet_option",
            "test_a_person_can_add_a_note_to_a_strike_from_the_profile",
            "test_nobody_else_can_add_a_note_to_someones_strike",
            "test_outsiders_get_a_404",
            "test_text_is_required",
            "test_the_report_page_and_saving",
            "test_the_trips_page_links_to_report_only_when_it_makes_sense",
        ],
    },
    "apps/trust/tests/test_ratings.py": {
        "RatingViewTests": [
            "test_a_missing_star_count_shows_an_error",
            "test_an_outsider_gets_a_404",
            "test_anonymous_goes_to_login",
            "test_ratings_show_on_search_cards_the_ride_page_and_the_profile",
            "test_search_cards_show_the_driver_rating",
            "test_the_driver_rating_a_rider_is_not_offered_safe_driving",
            "test_the_rate_page_and_saving",
            "test_the_trips_page_offers_rating_until_it_is_done",
        ],
    },
}

CLASS_LINES_TO_REMOVE = {
    "apps/accounts/tests/test_phone.py": [
        ("SignupPhoneTests", "url = reverse(\"accounts:register\")"),
    ],
    "apps/bookings/tests/test_trips_page.py": [
        ("TripsPageTests", "url = reverse(\"bookings:trips\")"),
        ("CallIconTests", "url = reverse(\"bookings:trips\")"),
    ],
    "apps/rides/tests/test_my_rides.py": [
        ("OfferedRidesPageTests", "url = reverse(\"rides:mine\")"),
    ],
}



def say(text):
    print(("[dry run] " if DRY_RUN else "") + text)


def delete_path(rel):
    if not os.path.exists(rel):
        say(f"skip (not there): {rel}")
        return 0
    say(f"delete: {rel}")
    if not DRY_RUN:
        shutil.rmtree(rel) if os.path.isdir(rel) else os.remove(rel)
    return 1


def strip_tests(rel, methods, class_lines):
    """Take the named tests (and a few lines at the top of classes) out of one test file, by line numbers,
    so the rest of the file keeps its formatting."""
    if not os.path.exists(rel):
        say(f"skip (not there): {rel}")
        return 0
    source = open(rel, encoding="utf-8").read()
    lines = source.split("\n")
    tree = ast.parse(source)
    kill = []
    removed = 0
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        names = methods.get(node.name, [])
        tests = [i for i in node.body if isinstance(i, ast.FunctionDef) and i.name.startswith("test_")]
        if tests and all(t.name in names for t in tests):  # every test of this class goes, so the class goes
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            kill.append((start, node.end_lineno))
            removed += len(tests)
            continue
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name in names:
                start = min([item.lineno] + [d.lineno for d in item.decorator_list])
                kill.append((start, item.end_lineno))
                removed += 1
            elif isinstance(item, ast.Assign) and (node.name, ast.get_source_segment(source, item)) in class_lines:
                kill.append((item.lineno, item.end_lineno))
    for start, end in sorted(kill, reverse=True):
        del lines[start - 1:end]
    text = "\n".join(lines)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")
    say(f"strip {removed} old-page test(s): {rel}")
    if not DRY_RUN:
        open(rel, "w", encoding="utf-8").write(text.rstrip("\n") + "\n")
    return removed


def main():
    if not os.path.exists("manage.py"):
        sys.exit("Run this from the project folder, the one that has manage.py.")
    count = sum(delete_path(p) for p in FOLDERS_TO_DELETE + FILES_TO_DELETE + TEST_FILES_TO_DELETE)
    removed = 0
    for rel in sorted(set(TEST_METHODS_TO_REMOVE) | set(CLASS_LINES_TO_REMOVE)):
        removed += strip_tests(rel, TEST_METHODS_TO_REMOVE.get(rel, {}), CLASS_LINES_TO_REMOVE.get(rel, []))
    print(f"\n{count} files and folders deleted, {removed} old-page tests taken out of other files.")
    if DRY_RUN:
        print("That was a dry run. Nothing was changed. Run it again without --dry-run to do it.")


main()