import argparse
import os

# module imports live inside the setup functions below: several modules pull in
# utils.slack; deferring imports keeps unrelated integrations out of
# credential-free actions (e.g. setup-zoom in dummy mode).

# Prepare for tutorials
# 1. Go to /static/tutorials
# 2. Update the tutorial content as seen in the tut_X.md files.
# 3. Add/Remove tut_X.md files as necessary. Make sure they are consecutive in number

useDummyValues = True
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
        help="Use sitedata_mock and MOCKUP_SLACK_* credentials instead of live data and credentials.",
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
        help="CSV with columns registration_email, preferred_email, used by invite-authors-to-channels",
    )

    #### Possible actions ####
    # setup-zoom
    # setup-tutorial-channels
    # create-tutorial-channels
    # add-admins-to-tutorials
    # setup-tutorials-invite-attendees
    # setup-tutorials (compatibility: runs both stages)
    # setup-papers-setup-channels
    # setup-papers-create-channels
    # setup-papers-set-desc
    # setup-event-channels
    # create-event-channels
    # set-event-channel-desc
    # setup-lbd-channels
    # create-lbd-channels
    # invite-authors-to-channels
    # setup-music
    # setup-sponsors
    # remove-author-email
    # prepare-calendar
    # process-new-users

    parser.add_argument(
        "--action",
        help="action to run (for example setup-zoom, setup-tutorial-channels, create-tutorial-channels, add-admins-to-tutorials, setup-tutorials-invite-attendees, setup-papers-create-channels, setup-papers-set-desc, setup-event-channels, create-event-channels, set-event-channel-desc)",
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


def setupTutorials(eventsCsvFile, registrationDataCsvFile, followup_action):
    from modules.tutorials import Tutorials

    tutObj = Tutorials(eventsCsvFile, registrationDataCsvFile, useDummyValues)
    if followup_action == "setup-channels":
        tutObj.setupChannelNames()
    elif followup_action == "create-channels":
        tutObj.createSlackChannels(slackUtils)
    elif followup_action == "add-admins":
        tutObj.addAdminsToChannels(slackUtils)
    elif followup_action == "invite-attendees":
        tutObj.inviteAttendeesToChannels(slackUtils)
    elif followup_action == "all":
        tutObj.setupSlackChannels(slackUtils)
    else:
        raise ValueError(f"Unknown tutorial action: {followup_action}")


def setupPapers(data_path, papersCsvFile, eventsCsvFile, followup_action):
    from modules.papers import Papers

    paperObj = Papers(data_path, papersCsvFile, useDummyValues, eventsCsvFile)
    if followup_action == "setup-channels":
        paperObj.setupSlackChannels()
    elif followup_action == "create-channels":
        paperObj.createSlackChannels()
    elif followup_action == "invite-authors":
        paperObj.inviteAuthorsToChannels()
    elif followup_action == "set-desc":
        paperObj.setSlackChannelDescription()
    else:
        raise Exception(
            "Invalid followup action for papers: "
            + followup_action
            + ". Possible values are setup-channels, create-channels, invite-authors"
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
            "setup-tutorials-invite-attendees."
        )

    if "setup" in action or "process" in action or action in {
        "create-event-channels", "create-tutorial-channels", "create-lbd-channels", "set-event-channel-desc",
        "add-admins-to-tutorials", "invite-authors-to-channels",
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

    elif action == "setup-tutorials-invite-attendees":
        setupTutorials(
            os.path.join(data_path, "events.csv"),
            registration_csv,
            "invite-attendees",
        )

    elif action == "setup-tutorials":
        setupTutorials(
            os.path.join(data_path, "events.csv"),
            registration_csv,
            "all",
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

    elif action == "invite-authors-to-channels":
        from modules.author_channels import invite_authors_to_channels

        invite_authors_to_channels(
            data_path,
            args.cmt_csv,
            args.registration_csv or "local/registration/Registrant Details - latest.csv",
            args.preferred_emails_csv,
            useDummyValues,
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
            registration_csv,
            "invite-attendees",
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
