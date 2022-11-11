#!/usr/bin/python3

"""
Script to convert JUnit/Google Test report to Sonar Generic Test Report
"""

import argparse
from lxml import etree
import enum
import os, os.path
import re
import sys

GTEST_RE = re.compile(r'TEST.*\((.+),(.+)\)')


class TestMsgType(enum.Enum):
    """
    The type of test message.
    """
    failure = 1
    error = 2
    skipped = 3


test_msg_type_map = {
    TestMsgType.skipped: 'skipped',
    TestMsgType.failure: 'failure',
    TestMsgType.error: 'error'
}

test_msg_tag_map = {
    'skipped': TestMsgType.skipped,
    'failure': TestMsgType.failure,
    'error': TestMsgType.error
}


class TestMsg:
    """
    Test case message
    """

    def __init__(self, msg_type, short_msg, long_msg):
        self._msg_type = msg_type
        self._short_msg = short_msg if short_msg is not None else ''
        self._long_msg = long_msg if long_msg is not None else ''

    @property
    def msg_type(self):
        return self._msg_type

    @property
    def short_msg(self):
        return self._msg_type

    @property
    def long_msg(self):
        return self._long_msg


class TestCase:
    """
    Test case.
    """

    def __init__(self, name, duration, msg=None):
        self._name = name
        self._duration = duration
        self._msg = msg

    @property
    def name(self):
        return self._name

    @property
    def duration(self):
        return self._duration

    @property
    def msg(self):
        return self._msg


class SonarTestExcution:

    def __init__(self, file_path):
        self._file_path = file_path
        self._test_cases = []

    def add_test_case(self, test_case):
        self._test_cases.append(test_case)

    def add_test_cases(self, test_cases):
        self._test_cases += test_cases

    @property
    def test_cases(self):
        return self._test_cases

    @property
    def file_path(self):
        return self._file_path


class SonarTestExcutionsXmlSerializer:

    @staticmethod
    def serialize(test_executions):
        root = etree.Element('testExecutions', version='1')

        for execution in test_executions:
            file_tag = etree.SubElement(root, 'file', path=execution.file_path)

            for test_case in execution.test_cases:
                test_case_tag = etree.SubElement(file_tag, 'testCase', name=test_case.name, duration=test_case.duration)

                if test_case.msg is not None:
                    tag_name = test_msg_type_map[test_case.msg.msg_type]

                    msg_tag = etree.SubElement(test_case_tag, tag_name, message=str(test_case.msg.short_msg))
                    msg_tag.text = test_case.msg.long_msg

        return etree.tostring(root, pretty_print=True)


class GoogleTestReportParser:

    @staticmethod
    def parse(searching_folder_path, searching_report_file_pattern, gtest_src_path, gtest_file_pattern):
        test_name_to_source_name = GoogleTestReportParser.doParseSrcFolder(gtest_src_path, gtest_file_pattern)

        sonarTestExcutions = {}

        regexp = re.compile(searching_report_file_pattern)

        for dirName, subdirList, fileList in os.walk(searching_folder_path):
            for fileName in fileList:
                if regexp.search(fileName) is not None:
                    executionDict = GoogleTestReportParser.doParse(os.path.join(dirName, fileName),
                                                                   test_name_to_source_name)

                    for key, value in iter(executionDict.items()):
                        if key not in sonarTestExcutions:
                            sonarTestExcutions[key] = SonarTestExcution(key)

                        sonarTestExcutions[key].add_test_cases(value.test_cases)

        return sonarTestExcutions.values()

    @staticmethod
    def doParse(gtest_report_path, test_name_to_source_name):
        sonarTestExecutions = {}
        try:
            tree = etree.parse(gtest_report_path)
            testSuites = tree.xpath('/testsuites/testsuite')

            for testSuite in testSuites:
                test_suite_name = testSuite.get('name')

                testCases = testSuite.xpath('testcase')
                for testCase in testCases:
                    testName = '{0}.{1}'.format(test_suite_name, testCase.get('name'))

                    if testName in test_name_to_source_name:
                        test_file_name = test_name_to_source_name[testName]
                        if test_file_name not in sonarTestExecutions:
                            sonarTestExecutions[test_file_name] = SonarTestExcution(test_file_name)

                        sonarTestExecutions[test_file_name].add_test_case(
                            TestCase(testName,
                                     str(int(float(testCase.get('time')) * 1000)),
                                     JUnitTestReportParser.doParseMsg(testCase))
                        )
                    else:
                        print("Couldn't find test case named {} in source code. Skip it.".format(testName))

        except Exception as e:
            print("Can't parse report file of {0}. Skip it. due to {1}".format(gtest_report_path, e))

        return sonarTestExecutions

    @staticmethod
    def doParseSrcFolder(gtest_src_folder, gtest_file_pattern):
        test_name_to_source_name = {}

        regexp = re.compile(gtest_file_pattern)

        for dirName, subdirList, fileList in os.walk(gtest_src_folder):
            for fileName in fileList:
                if regexp.search(fileName) is not None:
                    file_path = os.path.join(dirName, fileName)
                    with open(file_path, 'r') as src_file:
                        for line in src_file:
                            match = GTEST_RE.search(line)
                            if match:
                                test_name_to_source_name[
                                    '{0}.{1}'.format(match.group(1).strip(), match.group(2).strip())] = file_path

        return test_name_to_source_name


class JUnitTestReportParser:

    @staticmethod
    def parse(searching_folder_path, searching_report_file_pattern):
        sonarTestExcutions = {}

        regexp = re.compile(searching_report_file_pattern)

        for dirName, subdirList, fileList in os.walk(searching_folder_path):
            for fileName in fileList:
                if regexp.search(fileName) is not None:
                    executionDict = JUnitTestReportParser.doParse(os.path.join(dirName, fileName))

                    for key, value in executionDict.iteritems():
                        if key not in sonarTestExcutions:
                            sonarTestExcutions[key] = SonarTestExcution(key)

                        sonarTestExcutions[key].add_test_cases(value.test_cases)

        return sonarTestExcutions.values()

    @staticmethod
    def doParse(report_file_path):
        sonarTestExecutions = {}
        try:
            tree = etree.parse(report_file_path)
            testCases = tree.xpath('/testsuite/testcase')

            for testCase in testCases:
                if testCase.get('file') not in sonarTestExecutions:
                    sonarTestExecutions[testCase.get('file')] = SonarTestExcution(testCase.get('file'))

                sonarTestExecutions[testCase.get('file')].add_test_case(
                    TestCase('{0}.{1}'.format(testCase.get('classname'), testCase.get('name')),
                             str(int(float(testCase.get('time')) * 1000)),
                             JUnitTestReportParser.doParseMsg(testCase))
                )

        except Exception as e:
            print("Can't parse report file of {0}. Skip it. due to {1}".format(report_file_path, e))

        return sonarTestExecutions

    @staticmethod
    def doParseMsg(test_case_node):
        if len(test_case_node) > 0:
            if test_case_node[0].tag in test_msg_tag_map:
                return TestMsg(test_msg_tag_map[test_case_node[0].tag],
                               test_case_node[0].get('message'),
                               test_case_node[0].text)
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Convert given JUnit/GoogleTest report to Sonar generic test report')

    parser.add_argument('-t', '--report_type',
                        type=str,
                        default='junit',
                        choices=['junit', 'gtest'],
                        help='to-be-converted report type',
                        required=True)

    parser.add_argument('-D', '--search_folder',
                        type=str,
                        help='where to search the report XML file',
                        required=True)

    parser.add_argument('-P', '--report_pattern',
                        type=str,
                        help='the pattern of report XML file name',
                        required=True)

    parser.add_argument('-o', '--output',
                        type=str,
                        help='where to output the new report XML',
                        required=True)

    parser.add_argument('--gtest_src_folder',
                        type=str,
                        help='where the gtest source is')

    parser.add_argument('--gtest_src_pattern',
                        type=str,
                        help='the pattern of the gtest source file name')

    args = parser.parse_args()

    test_cases = []
    if args.report_type == 'junit':
        test_cases = JUnitTestReportParser.parse(args.search_folder, args.report_pattern)
    elif args.report_type == 'gtest':
        if args.gtest_src_folder is None or args.gtest_src_pattern is None:
            print('for gtest report, the gtest source folder and gtest src file name pattern are required.')
            sys.exit(1)

        test_cases = GoogleTestReportParser.parse(args.search_folder, args.report_pattern, args.gtest_src_folder,
                                                  args.gtest_src_pattern)

    with open(args.output, 'wb') as file:
        file.write(SonarTestExcutionsXmlSerializer.serialize(test_cases))
