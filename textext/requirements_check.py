"""
This file is part of TexText, an extension for the vector
illustration program Inkscape.

Copyright (c) 2006-2022 TexText developers.

TexText is released under the 3-Clause BSD license. See
file LICENSE.txt or go to https://github.com/textext/textext
for full license details.

Classes for handling and checking of the dependencies required
to successfully run TexText.

For historic reasons this module provides very powerful mechanisms
to check if TexText is able to run, esp. when installed from the
command line. With most recent Inkscape versions
the number of dependencies have been heavily reduced but we keep this
module alive anyway.
"""
import logging
import os
import re
import subprocess
import sys
from .log_util import LoggingColors, get_level_colors, LOGLEVEL_VERBOSE, LOGLEVEL_SUCCESS, LOGLEVEL_UNKNOWN
from .environment import system_env


class TrinaryLogicValue(object):
    def __init__(self, value=None):
        if isinstance(value, TrinaryLogicValue):
            self.value = value.value
        else:
            self.value = value

    def __and__(self, rhs):
        if rhs.value == False or self.value == False:
            return TrinaryLogicValue(False)
        if rhs.value is None or self.value is None:
            return TrinaryLogicValue(None)
        return TrinaryLogicValue(True)

    def __or__(self, rhs):
        if rhs.value == True or self.value == True:
            return TrinaryLogicValue(True)
        if rhs.value is None or self.value is None:
            return TrinaryLogicValue(None)
        return TrinaryLogicValue(False)

    def __invert__(self):
        if self.value is None:
            return TrinaryLogicValue(None)
        return TrinaryLogicValue(not self.value)

    def __eq__(self, rhs):
        if isinstance(rhs, TrinaryLogicValue):
            return self.value is None and rhs.value is None or self.value == rhs.value
        return self.value is None and rhs is None or self.value == rhs

    def __ne__(self, rhs):
        return not self.__eq__(rhs)

    def __str__(self):
        return "TrinaryLogicValue(%s)" % self.value


class RequirementCheckResult(object):
    def __init__(self, value, messages, nested=None, is_and_node=False, is_or_node=False, is_not_node=False, **kwargs):
        self.value = TrinaryLogicValue(value)
        self.messages = messages
        self.nested = nested if nested is not None else []

        self.is_and_node = is_and_node
        self.is_or_node = is_or_node
        self.is_not_node = is_not_node
        self.is_critical = None
        self.kwargs = kwargs

    @property
    def color(self):
        if self.value == True:
            return get_level_colors()[0]["SUCCESS "][1]
        elif self.value == False:
            return get_level_colors()[0]["ERROR   "][1]
        else:
            return get_level_colors()[0]["UNKNOWN "][1]

    def print_to_logger(self, logger, offset=0, prefix="", parent=None):
        _, reset_color = get_level_colors()

        if self.is_critical:
            lvl = logging.CRITICAL
        elif self.value == True:
            lvl = LOGLEVEL_SUCCESS
        elif self.value == False:
            lvl = logging.INFO
        else:
            lvl = LOGLEVEL_UNKNOWN

        value_repr = {
            True: "Succ",
            False: "Fail",
            None: "Ukwn"
        }
        if self.nested:
            nest_symbol = "+ [%s]" % value_repr[self.value.value]
        else:
            nest_symbol = "* [%s]" % value_repr[self.value.value]

        if parent:
            if parent.is_and_node:
                tail = parent.color + "/-and-" + self.color + nest_symbol + reset_color
            elif parent.is_or_node:
                tail = parent.color + "/--or-" + self.color + nest_symbol + reset_color
            elif parent.is_not_node:
                tail = parent.color + "/-not-" + self.color + nest_symbol + reset_color
            else:
                tail = parent.color + "/-----" + self.color + nest_symbol + reset_color
        else:
            tail = self.color + nest_symbol + reset_color

        if not parent:
            suffix = ""
        elif parent.nested[-1] is self:
            suffix = "      "
        else:
            suffix = parent.color + "|" + reset_color + "     "

        if not self.messages:
            messages = [""]
        else:
            messages = self.messages
        for msg in messages:
            line = ""
            line += prefix + tail
            line += " " + msg

            logger.log(lvl, line)

            tail = suffix
        for nst in self.nested:
            nst.print_to_logger(logger, offset + 1, prefix=prefix + suffix, parent=self)

    def flatten(self):
        if len(self.nested) == 0:
            return self

        for i, nst in enumerate(self.nested):
            self.nested[i] = nst.flatten()

        if self.nested[0].is_or_node and self.is_or_node:
            kwargs = dict(self.kwargs)
            kwargs.update(self.nested[0].kwargs)
            return RequirementCheckResult(
                self.value,
                self.nested[0].messages + self.messages,
                self.nested[0].nested + self.nested[1:],
                is_or_node=True,
                **kwargs
            )

        if self.nested[0].is_and_node and self.is_and_node:
            kwargs = dict(self.kwargs)
            kwargs.update(self.nested[0].kwargs)
            return RequirementCheckResult(
                self.value,
                self.nested[0].messages + self.messages,
                self.nested[0].nested + self.nested[1:],
                is_and_node=True,
                **kwargs
            )

        if self.nested[-1].is_or_node and self.is_or_node:
            kwargs = dict(self.kwargs)
            kwargs.update(self.nested[-1].kwargs)
            return RequirementCheckResult(
                self.value,
                self.messages + self.nested[-1].messages,
                self.nested[:-1] + self.nested[-1].nested,
                is_or_node=True,
                **kwargs
            )

        if self.nested[-1].is_and_node and self.is_and_node:
            kwargs = dict(self.kwargs)
            kwargs.update(self.nested[-1].kwargs)
            return RequirementCheckResult(
                self.value,
                self.messages + self.nested[-1].messages,
                self.nested[:-1] + self.nested[-1].nested,
                is_and_node=True,
                **kwargs
            )

        if self.nested[-1].is_not_node:
            self.kwargs.update(self.nested[-1].kwargs)

        return self

    def mark_critical_errors(self, non_critical_value=True):
        if self.value == non_critical_value:
            return
        if self.value == None:
            return

        self.is_critical = True

        if self.is_and_node or self.is_or_node:
            for nst in self.nested:
                if nst.value != non_critical_value:
                    nst.mark_critical_errors(non_critical_value)

        if self.is_not_node:
            for nst in self.nested:
                nst.mark_critical_errors(not non_critical_value)

    def __getitem__(self, item):
        return self.kwargs[item]


class Requirement(object):
    def __init__(self, criteria, *args, **kwargs):
        self.criteria = lambda: criteria(*args, **kwargs)
        self._prepended_messages = {"ANY": [], "SUCCESS": [], "ERROR": [], "UNKNOWN": []}
        self._appended_messages = {"ANY": [], "SUCCESS": [], "ERROR": [], "UNKNOWN": []}
        self._overwrite_messages = None

        self._on_unknown_callbacks = []
        self._on_success_callbacks = []
        self._on_failure_callbacks = []

    def check(self):
        result = self.criteria()
        if not isinstance(result.messages,list):
            result.messages = [result.messages]
        if self._overwrite_messages:
            result.messages = self._overwrite_messages
        result.messages = self._prepended_messages["ANY"] + result.messages
        if result.value == TrinaryLogicValue(True):
            result.messages = self._prepended_messages["SUCCESS"] + result.messages
            for callback in self._on_success_callbacks:
                callback(result)
        if result.value == TrinaryLogicValue(False):
            result.messages = self._prepended_messages["ERROR"] + result.messages
            for callback in self._on_failure_callbacks:
                callback(result)
        if result.value == TrinaryLogicValue(None):
            result.messages = self._prepended_messages["UNKNOWN"] + result.messages
            for callback in self._on_unknown_callbacks:
                callback(result)

        result.messages += self._appended_messages["ANY"]
        if result.value == TrinaryLogicValue(True):
            result.messages += self._appended_messages["SUCCESS"]
        if result.value == TrinaryLogicValue(False):
            result.messages += self._appended_messages["ERROR"]
        if result.value == TrinaryLogicValue(None):
            result.messages += self._appended_messages["UNKNOWN"]
        return result

    def prepend_message(self, result_type, message):
        assert result_type in self._prepended_messages.keys()
        if not isinstance(message, list):
            message = [message]
        self._prepended_messages[result_type].extend(message)
        return self

    def overwrite_check_message(self, message):
        if not isinstance(message, list):
            message = [message]
        self._overwrite_messages = message
        return self

    def append_message(self, result_type, message):
        assert result_type in self._appended_messages.keys()
        if not isinstance(message, list):
            message = [message]
        self._appended_messages[result_type].extend(message)
        return self

    def __and__(self, rhs):
        # type: (Requirement) -> Requirement
        def and_impl():
            L = self.check()
            R = rhs.check()
            return RequirementCheckResult(L.value & R.value,
                                          [],
                                          [L, R],
                                          is_and_node=True
                                          )

        return Requirement(and_impl)

    def __or__(self, rhs):
        # type: (Requirement) -> Requirement
        def or_impl():
            L = self.check()
            R = rhs.check()
            return RequirementCheckResult(L.value | R.value,
                                          [],
                                          [L, R],
                                          is_or_node=True
                                          )

        return Requirement(or_impl)

    def __invert__(self):
        # type: (Requirement) -> Requirement
        def invert_impl():
            L = self.check()
            return RequirementCheckResult(~L.value,
                                          [],
                                          [L],
                                          is_not_node=True
                                          )

        return Requirement(invert_impl)

    def on_success(self, callback):
        self._on_success_callbacks.append(callback)
        return self

    def on_failure(self, callback):
        self._on_failure_callbacks.append(callback)
        return self

    def on_unknown(self, callback):
        self._on_unknown_callbacks.append(callback)
        return self


class TexTextRequirementsChecker(object):

    def __init__(self, logger, config):
        self.logger = logger
        self.config = config
        self.available_tex_to_pdf_converters = {}
        self.available_pdf_to_svg_converters = {}

        self.inkscape_prog_name = "inkscape"
        self.pdflatex_prog_name = "pdflatex"
        self.lualatex_prog_name = "lualatex"
        self.xelatex_prog_name = "xelatex"

        self.inkscape_executable = None

        self.pygtk_is_found = False
        self.tkinter_is_found = False

        pass

    def find_pygtk3(self):
        try:
            executable = sys.executable
            system_env.call_command([executable, "-c", "import gi;" +
                                     "gi.require_version('Gtk', '3.0');" +
                                     "from gi.repository import Gtk, Gdk, GdkPixbuf"])
        except (KeyError, OSError, subprocess.CalledProcessError):
            return RequirementCheckResult(False, ["GTK3 is not found"])
        return RequirementCheckResult(True, ["GTK3 is found"])

    def find_tkinter(self):
        executable = sys.executable
        if sys.version_info[0] == 3:
            import_tk_script = "import tkinter; import tkinter.messagebox; import tkinter.filedialog;"
        else:
            import_tk_script = "import Tkinter; import tkMessageBox; import tkFileDialog;"
        try:
            system_env.call_command(
                [executable, "-c", import_tk_script])
        except (KeyError, OSError, subprocess.CalledProcessError):
            return RequirementCheckResult(False, ["TkInter is not found"])

        return RequirementCheckResult(True, ["TkInter is found"])

    def find_inkscape_1_0(self):
        try:
            executable = self.find_executable('inkscape')['path']
            stdout, stderr = system_env.call_command([executable, "--version"])
        except (KeyError, OSError):
            return RequirementCheckResult(False, ["inkscape is not found"])
        for stdout_line in stdout.decode("utf-8", 'ignore').split("\n"):
            m = re.search(r"Inkscape ((\d+)\.(\d+)[-\w]*)", stdout_line)

            if m:
                found_version, major, minor = m.groups()
                if int(major) >= 1:
                    return RequirementCheckResult(True, ["inkscape=%s is found" % found_version], path=executable)
                else:
                    return RequirementCheckResult(False, [
                        "inkscape>=1.0 is not found (but inkscape=%s is found)" % (found_version)])
        return RequirementCheckResult(None, ["Can't determinate inkscape version"])

    def find_executable(self, prog_name):
        # try value from config
        executable_path = self.config.get(prog_name+"-executable", None)
        if executable_path is not None:
            if self.check_executable(executable_path):
                self.logger.info("Using `%s-executable` = `%s`" % (prog_name, executable_path))
                return RequirementCheckResult(True, "%s is found at `%s`" % (prog_name, executable_path),
                                              path=executable_path)
            else:
                self.logger.warning("Bad `%s` executable: `%s`" % (prog_name, executable_path))
                self.logger.warning("Fall back to automatic detection of `%s`" % prog_name)
        # look for executable in path
        return self._find_executable_in_path(prog_name)

    def _find_executable_in_path(self, prog_name):
        messages = []
        for exe_name in system_env.executable_names[prog_name]:
            first_path = None
            for path in system_env.get_system_path():
                full_path_guess = os.path.join(path, exe_name)
                self.logger.log(LOGLEVEL_VERBOSE, "Looking for `%s` in `%s`" % (exe_name, path))
                if self.check_executable(full_path_guess):
                    self.logger.log(LOGLEVEL_VERBOSE, "`%s` is found at `%s`" % (exe_name, path))
                    messages.append("`%s` is found at `%s`" % (exe_name, path))
                    if first_path is None:
                        first_path = path
            if first_path is not None:
                return RequirementCheckResult(True, messages, path=os.path.join(first_path,exe_name))
            messages.append("`%s` is NOT found in PATH" % (exe_name))
        return RequirementCheckResult(False, messages)

    def check_executable(self, filename):
        return filename is not None and os.path.isfile(filename) and os.access(filename, os.X_OK)

    def check(self):

        def set_inkscape(exe):
            self.inkscape_executable = exe

        def add_latex(name, exe):
            self.available_tex_to_pdf_converters.update({name: exe})

        def set_pygtk(result):
            self.pygtk_is_found = True

        def set_tkinter(result):
            self.tkinter_is_found= True

        def help_message_with_url(section_name, executable_name=None):
            user = "textext"
            url_template = "https://{user}.github.io/textext/install/{os_name}.html#{os_name}-install-{section}"
            url = url_template.format(
                user=user,
                os_name=system_env.os_name,
                section=section_name
            )

            if system_env.console_colors == "always":
                url_line = "       {}%s{}".format(LoggingColors.FG_LIGHT_BLUE + LoggingColors.UNDERLINED,
                                                     LoggingColors.COLOR_RESET)
            else:
                url_line = "       {}%s{}".format("", "")

            result = [
                "Please follow installation instructions at ",
                url_line % url
            ]
            if executable_name:
                result += [
                    "If %s is installed in custom location, specify it via " % executable_name,
                    "       --{name}-executable=<path-to-{name}>".format(name=executable_name),
                    "and run setup.py again",
                ]
            return result

        textext_requirements = (
            Requirement(self.find_inkscape_1_0)
            .prepend_message("ANY", 'Detect inkscape>=1.0')
            .append_message("ERROR", help_message_with_url("preparation","inkscape"))
            .on_success(lambda result: set_inkscape(result["path"]))
            & (
                    Requirement(self.find_executable, self.pdflatex_prog_name)
                    .on_success(lambda result: add_latex("pdflatex", result["path"]))
                    .append_message("ERROR", help_message_with_url("preparation", "pdflatex"))
                    | Requirement(self.find_executable, self.lualatex_prog_name)
                    .on_success(lambda result: add_latex("lualatex", result["path"]))
                    .append_message("ERROR", help_message_with_url("preparation", "lualatex"))
                    | Requirement(self.find_executable, self.xelatex_prog_name)
                    .on_success(lambda result: add_latex("xelatex", result["path"]))
                    .append_message("ERROR", help_message_with_url("preparation", "xelatex"))
            ).overwrite_check_message("Detect *latex")
            .append_message("ERROR", help_message_with_url("preparation"))
            & (
                    Requirement(self.find_pygtk3).on_success(set_pygtk)
                    .append_message("ERROR", help_message_with_url("gtk3"))
                    | Requirement(self.find_tkinter).on_success(set_tkinter)
                    .append_message("ERROR", help_message_with_url("tkinter"))
            ).overwrite_check_message("Detect GUI library")
            .append_message("ERROR", help_message_with_url("gui-library"))
        ).overwrite_check_message("TexText requirements")

        check_result = textext_requirements.check()

        check_result = check_result.flatten()

        check_result.mark_critical_errors()

        check_result.print_to_logger(self.logger)

        return check_result.value



