import argparse
import os
from pathlib import Path

# module imports live inside the setup functions below: several modules pull in
# utils.slack; deferring imports keeps unrelated integrations out of
# credential-free actions (e.g. setup-zoom in dummy mode).

# Prepare for tutorials
# 1. Go to /static/tutorials
# 2. Update the tutorial content as seen in the tut_X.md files.
# 3. Add/Remove tut_X.md files as necessary. Make sure they are consecutive in number

useDummyValues = True
# ConferenceCatalysts "Registrant Details" export, used by author and tutorial channel assignment
REGISTRATION_EXPORT_CSV = "local/registration/Registrant Details - latest.csv"
DEFAULT_REGISTRATION_CSV = (
    "__23rd_International_Society_for_Music_Information_Retrieval_Conference_"
    "(ISMIR_2022)__Registration_Data.csv"
)


def prompt_for_zoom_passcode():
    return input(
        "Enter shared passcode for webinar and all poster meetings: "
    ).strip()


def parse_arguments():
    parser = argparse.ArgumentParser(description="MiniConf Prep Script")

    parser.add_argument(
        "--mockup",
        action="store_true",
        help="Use sitedata_mock instead of live data. Slack actions require mockup.env to be loaded.",
    )

    parser.add_argument(
        "--prod",
        help="set this value as true if we want to run on prod data.",
        default=False,
    )

    parser.add_argument(
        "--registration-csv",
        help="registration CSV used by tutorial/sponsor attendee assignment",
    )

    parser.add_argument(
        "--cmt-csv",
        default="local/cmt_authors.csv",
        help="CMT author export (Paper ID, Author Names, Author Emails) used by invite-authors-to-channels",
    )

    parser.add_argument(
        "--preferred-emails-csv",
        help="Google Form export (timestamp, preferred email, registration email), required by add-registrants-to-tutorials, process-new-users, invite-authors-to-channels and invite-authors-to-lbd-group-channels",
    )

    #### Possible actions ####
    # setup-zoom
    # setup-tutorial-channels
    # create-tutorial-channels
    # add-admins-to-tutorials
    # add-registrants-to-tutorials
    # setup-papers-setup-channels
    # setup-papers-create-channels
    # setup-papers-set-desc
    # setup-event-channels
    # create-event-channels
    # set-event-channel-desc
    # setup-lbd-channels
    # create-lbd-channels
    # setup-lbd-group-channels
    # create-lbd-group-channels
    # invite-authors-to-channels
    # invite-authors-to-lbd-group-channels
    # setup-music
    # setup-sponsors
    # remove-author-email
    # prepare-calendar
    # process-new-users

    parser.add_argument(
        "--action",
        help="action to run (for example setup-zoom, setup-tutorial-channels, create-tutorial-channels, add-admins-to-tutorials, add-registrants-to-tutorials, setup-papers-create-channels, setup-papers-set-desc, setup-event-channels, create-event-channels, set-event-channel-desc)",
        required=True,
    )

    args = parser.parse_args()
    return args


# Step1: Create Slack channels and Zoom links 
def setupZoom(eventsCsvFile, papersCsvFile=None, passcode=None, is_mockup=False):
    from modules.zoom_creator import ZoomCreator

    if passcode is None and not useDummyValues:
        passcode = prompt_for_zoom_passcode()
    zoomCreator = ZoomCreator(eventsCsvFile, useDummyValues, papersCsvFile,
                              topicPrefix="mock-" if is_mockup else "")
    zoomCreator.setupZoomCalls(zoomUtils, passcode=passcode)


def setupTutorials(eventsCsvFile, registrationDataCsvFile, followup_action, preferredEmailsCsvFile=None):
    from modules.tutorials import Tutorials
    from utils.identity import load_preferred_emails

    preferred = load_preferred_emails(Path(preferredEmailsCsvFile), Path(registrationDataCsvFile)) if preferredEmailsCsvFile else None
    tutObj = Tutorials(eventsCsvFile, registrationDataCsvFile, useDummyValues, preferred)
    if followup_action == "setup-channels":
        tutObj.setupChannelNames()
    elif followup_action == "create-channels":
        tutObj.createSlackChannels(slackUtils)
    elif followup_action == "add-admins":
        tutObj.addAdminsToChannels(slackUtils)
    elif followup_action == "add-registrants":
        tutObj.addRegistrantsToChannels(slackUtils)
    else:
        raise ValueError(f"Unknown tutorial action: {followup_action}")


def setupPapers(data_path, papersCsvFile, eventsCsvFile, followup_action):
    from modules.papers import Papers

    paperObj = Papers(data_path, papersCsvFile, useDummyValues, eventsCsvFile)
    if followup_action == "setup-channels":
        paperObj.setupSlackChannels()
    elif followup_action == "create-channels":
        paperObj.createSlackChannels()
    elif followup_action == "set-desc":
        paperObj.setSlackChannelDescription()
    else:
        raise Exception(
            "Invalid followup action for papers: "
            + followup_action
            + ". Possible values are setup-channels, create-channels, set-desc"
        )


def setupEventChannels(eventsCsvFile):
    from modules.events import Events

    eventsObj = Events(eventsCsvFile, useDummyValues)
    eventsObj.setupSlackChannels()


def createEventChannels(eventsCsvFile):
    from modules.events import Events

    eventsObj = Events(eventsCsvFile, useDummyValues)
    eventsObj.createSlackChannels()


def setEventChannelDesc(data_path):
    from utils.slack import batch_set_channel_description_interactive

    batch_set_channel_description_interactive(data_path)

def setupLbdChannels(lbdCsvFile):
    from modules.lbds import Lbds

    Lbds(lbdCsvFile).setupSlackChannels()


def createLbdChannels(lbdCsvFile):
    from modules.lbds import Lbds

    Lbds(lbdCsvFile).createSlackChannels()


def setupLbdGroupChannels(groupingCsvFile):
    from modules.lbds import LbdGroups

    LbdGroups(groupingCsvFile).setupSlackChannels()


def createLbdGroupChannels(groupingCsvFile):
    from modules.lbds import LbdGroups

    LbdGroups(groupingCsvFile).createSlackChannels()


def setupMusic(musicCsvFile):
    from modules.music import Music

    musicObj = Music(musicCsvFile, useDummyValues)
    musicObj.setupSlackChannels(slackUtils)


def setupSponsors(industryCsvFile, registrtionDataCsvFile):
    from modules.industry import Industry

    industryObj = Industry(industryCsvFile, registrtionDataCsvFile, useDummyValues)
    industryObj.setupSlackChannels(slackUtils)


def removeAuthorEmails():
    from scripts.remove_private_details import remove_author_contacts

    remove_author_contacts()


if __name__ == "__main__":
    args = parse_arguments()
    data_path = "sitedata_mock" if args.mockup else "sitedata"
    useDummyValues = not args.prod
    action = args.action
    registration_csv = args.registration_csv or (
        os.path.join(data_path, DEFAULT_REGISTRATION_CSV) if data_path else None
    )

    if action is None:
        raise Exception(
            "--action is missing. See --help for available actions, including "
            "create-tutorial-channels and "
            "add-registrants-to-tutorials."
        )

    if action in {
        "add-registrants-to-tutorials", "process-new-users",
        "invite-authors-to-channels", "invite-authors-to-lbd-group-channels",
    } and not args.preferred_emails_csv:
        raise Exception(f"--preferred-emails-csv is required for {action}.")

    if "setup" in action or "process" in action or action in {
        "create-event-channels", "create-tutorial-channels", "create-lbd-channels", "create-lbd-group-channels",
        "set-event-channel-desc",
        "add-admins-to-tutorials", "add-registrants-to-tutorials", "invite-authors-to-channels",
        "invite-authors-to-lbd-group-channels",
    }:
        if action == "setup-zoom":
            # zoom creds are only checked on first API call, so this import is
            # safe without .env and setup-zoom never needs SLACK_BOT_TOKEN
            from utils import zoom as zoomUtils
        else:
            from utils import slack as slackUtils

            slackUtils.configure_clients(is_mockup=args.mockup)

    if action == "setup-zoom":
        setupZoom(
            os.path.join(data_path, "events.csv"),
            os.path.join(data_path, "papers.csv"),
            passcode=None,
            is_mockup=args.mockup,
        )

    elif action == "setup-tutorial-channels":
        setupTutorials(os.path.join(data_path, "events.csv"), None, "setup-channels")

    elif action == "create-tutorial-channels":
        setupTutorials(
            os.path.join(data_path, "events.csv"),
            None,
            "create-channels",
        )

    elif action == "add-admins-to-tutorials":
        setupTutorials(os.path.join(data_path, "events.csv"), None, "add-admins")

    elif action == "add-registrants-to-tutorials":
        setupTutorials(
            os.path.join(data_path, "events.csv"),
            args.registration_csv or REGISTRATION_EXPORT_CSV,
            "add-registrants",
            args.preferred_emails_csv,
        )

    elif action.startswith("setup-papers-"):
        folowup_action = action.replace("setup-papers-", "")
        setupPapers(
            data_path,
            os.path.join(data_path, "papers.csv"),
            os.path.join(data_path, "events.csv"),
            folowup_action,
        )

    elif action == "setup-event-channels":
        setupEventChannels(os.path.join(data_path, "events.csv"))

    elif action == "create-event-channels":
        createEventChannels(os.path.join(data_path, "events.csv"))
    
    elif action == "set-event-channel-desc":
        setEventChannelDesc(data_path)

    elif action == "setup-lbd-channels":
        setupLbdChannels(os.path.join(data_path, "lbds.csv"))

    elif action == "create-lbd-channels":
        createLbdChannels(os.path.join(data_path, "lbds.csv"))

    elif action == "setup-lbd-group-channels":
        setupLbdGroupChannels(os.path.join(data_path, "lbds_grouping.csv"))

    elif action == "create-lbd-group-channels":
        createLbdGroupChannels(os.path.join(data_path, "lbds_grouping.csv"))

    elif action in ("invite-authors-to-channels", "invite-authors-to-lbd-group-channels"):
        from modules.author_channels import invite_authors_to_channels

        invite_authors_to_channels(
            data_path,
            args.cmt_csv,
            args.registration_csv or REGISTRATION_EXPORT_CSV,
            args.preferred_emails_csv,
            useDummyValues,
            lbd_groups=action == "invite-authors-to-lbd-group-channels",
        )

    elif action == "setup-music":
        setupMusic(os.path.join(data_path, "music.csv"))

    elif action == "setup-sponsors":
        setupSponsors(
            os.path.join(data_path, "industry.csv"),
            registration_csv,
        )

    elif action == "process-new-users":
        # First setup tutorials.
        setupTutorials(
            os.path.join(data_path, "events.csv"),
            args.registration_csv or REGISTRATION_EXPORT_CSV,
            "add-registrants",
            args.preferred_emails_csv,
        )
        # Next setup sponsors.
        setupSponsors(
            os.path.join(data_path, "industry.csv"),
            registration_csv,
        )

    elif action == "remove-author-email":
        removeAuthorEmails()

    elif action == "prepare-calendar":
        # Step3: Prepare for calendar
        # If links from schedule are not redirecting to the right page, check this code
        from scripts.calendar_csv2ics import calendar_csv2ics

        calendar_csv2ics(in_csv=os.path.join(data_path, "events.csv"))
