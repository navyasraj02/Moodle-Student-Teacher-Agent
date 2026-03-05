"""
Student and Teacher agent flows.
Each step: navigate to URL -> send page to LLM -> LLM returns semantic selectors -> execute.
Full LLM I/O is printed at every step.
"""
import os
import asyncio
from browser import BrowserController
from llm import create_llm_client, analyze_page, generate_assignment_response, generate_feedback
from utils import logger, print_step

MAX_RETRIES = 3


# ======================= Base agent =======================

class MoodleAgent:
    def __init__(self, headless: bool = False):
        self.browser = BrowserController(headless=headless)
        self.llm = create_llm_client()
        self.base = os.getenv("MOODLE_URL", "http://127.0.0.1:8080")

    async def start(self):
        await self.browser.start()

    async def close(self):
        await self.browser.close()

    # Helper: ask LLM what to do on the current page, then execute
    async def ask_and_act(self, task: str, step_name: str = "") -> dict:
        """Get page summary -> send to LLM -> execute returned actions."""
        page_summary = await self.browser.get_page_summary()
        plan = await analyze_page(self.llm, page_summary, task, step_name=step_name)
        actions = plan.get("actions", [])
        if actions:
            await self.browser.execute_actions(actions)
            await self.browser.wait_for_load()
        return plan

    # Helper: repeat ask_and_act until LLM says done or max tries
    async def ask_until_done(self, task: str, step_name: str = "", max_tries: int = MAX_RETRIES) -> bool:
        for attempt in range(max_tries):
            plan = await self.ask_and_act(task, step_name=f"{step_name} (attempt {attempt+1})")
            if plan.get("done"):
                return True
        return False


# ======================= Student Agent =======================

class StudentAgent(MoodleAgent):
    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self.username = os.getenv("STUDENT_USER", "student1")
        self.password = os.getenv("STUDENT_PASS", "")

    async def run(self):
        logger.info("=== Starting Student Agent ===")
        await self.start()
        try:
            await self.step_login()
            course_url = await self.step_find_course()
            assignments = await self.step_list_assignments()

            while assignments:
                asgn = assignments.pop(0)
                logger.info(f"Checking assignment: {asgn['text']}")

                needs_submit = await self.step_check_unsubmitted(asgn)
                if needs_submit:
                    await self.step_submit_assignment(asgn)

                # Return to course page for next assignment
                print_step("RETURN TO COURSE", course_url)
                await self.browser.navigate(course_url)
                await self.browser.wait_for_load()

            logger.info("All assignments processed.")
        finally:
            await self.close()
        logger.info("=== Student Agent finished ===")

    # ---- Step 1: Login ----
    async def step_login(self):
        url = f"{self.base}/login/index.php"
        print_step("LOGIN", url)
        await self.browser.navigate(url)
        await self.browser.wait_for_load()

        task = (
            f"Log into Moodle. Fill the username field with '{self.username}' "
            f"and the password field with '{self.password}', then click the login button."
        )
        for _ in range(MAX_RETRIES):
            plan = await self.ask_and_act(task, step_name="LOGIN")
            await self.browser.wait_for_load()
            if await self.browser.has_text("Dashboard") or await self.browser.has_text("My courses"):
                logger.info("Login successful")
                return
        raise Exception("Login failed")

    # ---- Step 2: Find course ----
    async def step_find_course(self) -> str:
        print_step("FIND COURSE", "Navigate to My courses then open the first course")

        # First, navigate to My courses page
        task_my_courses = (
            "Click on 'My courses' navigation link/tab to see the list of enrolled courses."
        )
        await self.ask_and_act(task_my_courses, step_name="NAVIGATE TO MY COURSES")
        await self.browser.wait_for_load()

        # Extract course links directly (more reliable than clicking ambiguous text)
        logger.info("Looking for course links on page...")
        all_links = await self.browser.extract_links("")
        course_links = [
            link for link in all_links
            if "/course/view.php" in link.get("href", "")
        ]

        if course_links:
            first_course = course_links[0]
            logger.info(f"Found course: {first_course['text']} -> {first_course['href']}")
            
            # Navigate directly to the course URL (avoids ambiguous element clicking)
            href = first_course["href"]
            if not href.startswith("http"):
                href = f"{self.base}{href}" if href.startswith("/") else f"{self.base}/{href}"
            
            await self.browser.navigate(href)
            await self.browser.wait_for_load()
            
            current = await self.browser.get_current_url()
            if "/course/view.php" in current:
                logger.info(f"Successfully opened course: {current}")
                return current
        
        # Fallback: try LLM-guided clicking if direct link extraction failed
        logger.warning("Direct link extraction failed, trying LLM guidance...")
        task_open_course = (
            "Click on the FIRST course link/card to open it. "
            "Look for a clickable course title or card. "
            "Do NOT click Home, Dashboard, Grades, or admin links."
        )
        for _ in range(MAX_RETRIES):
            await self.ask_and_act(task_open_course, step_name="OPEN FIRST COURSE")
            current = await self.browser.get_current_url()
            if "/course/view.php" in current:
                logger.info(f"On course page: {current}")
                return current
        raise Exception("Could not reach course page")

    # ---- Step 3: List assignments ----
    async def step_list_assignments(self) -> list[dict]:
        print_step("LIST ASSIGNMENTS", "Find all assignment links on course page")

        links = await self.browser.extract_links("assign")
        assignments = [l for l in links if "/mod/assign/view.php" in l.get("href", "")]

        if not assignments:
            # Let LLM try to find assignment links
            task = "List all assignment links visible on this course page."
            plan = await self.ask_and_act(task, step_name="LIST ASSIGNMENTS (LLM)")
            # Re-extract after possible navigation
            links = await self.browser.extract_links("assign")
            assignments = [l for l in links if "/mod/assign/view.php" in l.get("href", "")]

        logger.info(f"Found {len(assignments)} assignment(s):")
        for a in assignments:
            logger.info(f"  - {a['text']}  ({a['href']})")
        return assignments

    # ---- Step 4: Check if unsubmitted ----
    async def step_check_unsubmitted(self, assignment: dict) -> bool:
        href = assignment["href"]
        if not href.startswith("http"):
            href = f"{self.base}{href}" if href.startswith("/") else f"{self.base}/{href}"
        print_step("CHECK SUBMISSION STATUS", href)
        await self.browser.navigate(href)
        await self.browser.wait_for_load()

        task = (
            "Look at this assignment page and determine the submission status. "
            "If it says 'No submission' or 'No attempt' or you see an 'Add submission' button, "
            "set done=false (needs submission). "
            "If it says 'Submitted for grading' or already submitted, set done=true."
        )
        plan = await self.ask_and_act(task, step_name="CHECK STATUS")
        page_text = (await self.browser._get_main_text()).lower()

        already_done = plan.get("done", False)
        if already_done or ("submitted for grading" in page_text and "no submission" not in page_text):
            logger.info(f"Already submitted: {assignment['text']}")
            return False

        logger.info(f"Needs submission: {assignment['text']}")
        return True

    # ---- Step 5: Submit assignment ----
    async def step_submit_assignment(self, assignment: dict):
        print_step("SUBMIT ASSIGNMENT", assignment["text"])

        # 5a. Get assignment instructions before clicking submit
        instructions = await self.browser._get_main_text()

        # 5b. Click "Add submission"
        task_open = (
            "Open the submission form. Click the correct button or link such as "
            "'Add submission' or 'Edit submission'."
        )
        await self.ask_and_act(task_open, step_name="OPEN SUBMISSION FORM")

        # 5c. Generate answer using LLM
        draft = await generate_assignment_response(self.llm, instructions)
        logger.info(f"Generated answer: {draft[:120]}...")

        # 5d. Robustly handle multi-step editor visibility + fill + save
        for attempt in range(MAX_RETRIES):
            if not await self.browser.is_editor_visible():
                task_reveal = (
                    "Make the text editor visible for entering the submission. "
                    "If needed, click intermediary controls such as Edit/Add/Enable/Toggle/Expand. "
                    "Do not submit yet."
                )
                await self.ask_and_act(task_reveal, step_name=f"REVEAL EDITOR (attempt {attempt+1})")
                await self.browser.wait_for_load()

            task_fill = (
                f"Type this exact assignment answer into the main online text editor or text area:\n\n"
                f'"{draft}"\n\n'
                "Then click 'Save changes'. If a richer editor requires enabling editing first, do that before typing."
            )
            await self.ask_and_act(task_fill, step_name=f"FILL AND SAVE (attempt {attempt+1})")

            # Direct fallback for editors that are hard to target semantically
            await self._try_fill_editor(draft)
            if await self.browser.has_text("Save changes"):
                await self.browser.click("Save changes")

            await self.browser.wait_for_load()

            page_text = (await self.browser._get_main_text()).lower()
            if "submitted for grading" in page_text or "submission status" in page_text:
                break

        # 5e. Confirm submission if Moodle asks
        if await self.browser.has_text("Submit assignment"):
            task_confirm = "Click 'Submit assignment' to confirm the submission, then click 'Continue' if prompted."
            await self.ask_and_act(task_confirm, step_name="CONFIRM SUBMISSION")

        if await self.browser.has_text("Continue"):
            await self.browser.click("Continue")
            await self.browser.wait_for_load()

        logger.info(f"Submitted: {assignment['text']}")

    async def _try_fill_editor(self, text: str):
        """Try direct strategies for Moodle rich-text editors."""
        page = self.browser.page
        try:
            editor = await page.query_selector("[contenteditable='true']")
            if editor:
                await editor.click()
                await editor.fill(text)
                return
        except:
            pass
        try:
            await page.locator("textarea").first.fill(text)
        except:
            pass


# ======================= Teacher Agent =======================

class TeacherAgent(MoodleAgent):
    def __init__(self, headless: bool = False):
        super().__init__(headless)
        self.username = os.getenv("TEACHER_USER", "teacher1")
        self.password = os.getenv("TEACHER_PASS", "")

    async def run(self):
        logger.info("=== Starting Teacher Agent ===")
        await self.start()
        try:
            await self.step_login()
            course_url = await self.step_find_course()
            assignments = await self.step_list_assignments()

            while assignments:
                asgn = assignments.pop(0)
                has_ungraded = await self.step_check_ungraded(asgn)
                if has_ungraded:
                    await self.step_grade_assignment()

                print_step("RETURN TO COURSE", course_url)
                await self.browser.navigate(course_url)
                await self.browser.wait_for_load()

            logger.info("All assignments processed.")
        finally:
            await self.close()
        logger.info("=== Teacher Agent finished ===")

    # ---- Step 1: Login ----
    async def step_login(self):
        url = f"{self.base}/login/index.php"
        print_step("LOGIN", url)
        await self.browser.navigate(url)
        await self.browser.wait_for_load()

        task = (
            f"Log into Moodle. Fill the username field with '{self.username}' "
            f"and the password field with '{self.password}', then click the login button."
        )
        for _ in range(MAX_RETRIES):
            await self.ask_and_act(task, step_name="LOGIN")
            await self.browser.wait_for_load()
            if await self.browser.has_text("Dashboard") or await self.browser.has_text("My courses"):
                logger.info("Login successful")
                return
        raise Exception("Login failed")

    # ---- Step 2: Find course ----
    async def step_find_course(self) -> str:
        print_step("FIND COURSE", "Navigate to My courses then open the first course")

        task_my_courses = "Click on the 'My courses' navigation link/tab to see enrolled courses."
        await self.ask_and_act(task_my_courses, step_name="NAVIGATE TO MY COURSES")

        # Extract all links and find course links by URL pattern (avoid ambiguous text clicking)
        all_links = await self.browser.extract_links("")
        course_links = [link for link in all_links if "/course/view.php" in link.get("href", "")]

        if course_links:
            first_course = course_links[0]
            href = first_course["href"]
            logger.info(f"Found course link: {first_course['text']} → {href}")
            print_step("NAVIGATE TO COURSE", f"Directly navigating to: {href}")
            await self.browser.navigate(href)
            current = await self.browser.get_current_url()
            if "/course/view.php" in current:
                logger.info(f"On course page: {current}")
                return current

        # Fallback: LLM-driven clicking if direct extraction fails
        task_open = (
            "Click on the FIRST course link/card to open it. "
            "Do NOT click Home, Dashboard, Grades, or admin links."
        )
        for _ in range(MAX_RETRIES):
            await self.ask_and_act(task_open, step_name="OPEN FIRST COURSE")
            current = await self.browser.get_current_url()
            if "/course/view.php" in current:
                logger.info(f"On course page: {current}")
                return current
        raise Exception("Could not reach course page")

    # ---- Step 3: List assignments ----
    async def step_list_assignments(self) -> list[dict]:
        print_step("LIST ASSIGNMENTS", "Find all assignment links on course page")
        links = await self.browser.extract_links("assign")
        assignments = [l for l in links if "/mod/assign/view.php" in l.get("href", "")]

        logger.info(f"Found {len(assignments)} assignment(s):")
        for a in assignments:
            logger.info(f"  - {a['text']}  ({a['href']})")
        return assignments

    # ---- Step 4: Check for ungraded submissions ----
    async def step_check_ungraded(self, assignment: dict) -> bool:
        href = assignment["href"]
        if not href.startswith("http"):
            href = f"{self.base}{href}" if href.startswith("/") else f"{self.base}/{href}"
        print_step("CHECK UNGRADED", f"{assignment['text']}  ({href})")
        await self.browser.navigate(href)
        await self.browser.wait_for_load()

        # Try to view all submissions
        task = "Click 'View all submissions' or 'Grade' to see the grading overview table."
        await self.ask_and_act(task, step_name="OPEN GRADING VIEW")

        page_text = (await self.browser._get_main_text()).lower()
        if "needs grading" in page_text or "submitted" in page_text:
            logger.info("Found submissions to grade")
            return True
        logger.info("No submissions to grade")
        return False

    # ---- Step 5: Grade first ungraded submission ----
    async def step_grade_assignment(self):
        print_step("GRADE SUBMISSION", "Open first ungraded, enter grade, save")

        # Click Grade for first entry
        task_open = (
            "Find the first student submission that needs grading and click 'Grade' to open the grading form."
        )
        await self.ask_and_act(task_open, step_name="OPEN GRADE FORM")

        # Read submission for feedback
        submission_text = await self.browser._get_main_text()
        feedback = await generate_feedback(self.llm, submission_text)
        logger.info(f"Generated feedback: {feedback}")

        # Enter grade and feedback via LLM
        task_grade = (
            f"Enter the grade '100' into the grade field. "
            f"Then type this feedback into the feedback text area: \"{feedback}\". "
            f"Then click 'Save changes' or 'Save and show next'."
        )
        for _ in range(MAX_RETRIES):
            await self.ask_and_act(task_grade, step_name="ENTER GRADE AND SAVE")
            page_text = (await self.browser._get_main_text()).lower()
            if "grading" in page_text or "saved" in page_text or "changes saved" in page_text:
                break

        logger.info("Grade saved")


# ======================= Factory =======================

def create_agent(agent_type: str, headless: bool = False):
    if agent_type == "student":
        return StudentAgent(headless=headless)
    elif agent_type == "teacher":
        return TeacherAgent(headless=headless)
    else:
        raise ValueError(f"Unknown agent type: {agent_type}")
