# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
File type check test module
"""

import asyncio
import json
import logging
import os
import time
import urllib.parse
from typing import Any

import aiohttp

from ..base import BaseTestModule, TestStatus, test_case

logger = logging.getLogger(__name__)


class FileTypeCheckModule(BaseTestModule):
    """File type check test module"""

    TEST_FILE_TYPES_COLLECTION = "test_file_types"

    def __init__(self, test_runner):
        super().__init__(test_runner)
        self._task_id = None
        self._file_type_test_files = [
            "backup_script.sh",
            # "employment_bar_graph.svg",
            "factory_data.jpeg",
            "Global_Multimodal_data.pptx",
            # "global_warming_bar.tiff",
            # "India_population.bmp",
            "India_population.gif",
            "MF.md",
            "NFO.html",
            "PdM_machines.csv",
            "Product_Sales.png",
            "rag-metrics-dashboard.json",
            "stock_prices.jpg",
        ]

    @test_case(39, "Upload File Type Test Documents")
    async def _test_upload_file_types(self) -> bool:
        """Test uploading various file types to test file type support"""
        logger.info("\n=== Test 39: Upload File Type Test Documents ===")
        upload_start = time.time()

        # Get full file paths for the test files
        test_files = self._get_file_type_test_files()
        if not test_files:
            self.add_test_result(
                self._test_upload_file_types.test_number,
                self._test_upload_file_types.test_name,
                f"Upload various file types to test file type support. Collection: {self.TEST_FILE_TYPES_COLLECTION}. Files: {', '.join(self._file_type_test_files)}. Non-blocking mode with summary generation disabled.",
                ["POST /v1/documents"],
                [
                    "collection_name",
                    "blocking",
                    "generate_summary",
                    "split_options",
                ],
                time.time() - upload_start,
                TestStatus.FAILURE,
                "No test files found",
            )
            return False

        task_id = await self._upload_documents(
            self.TEST_FILE_TYPES_COLLECTION,
            test_files,
            blocking=False,
            generate_summary=False,
        )
        upload_time = time.time() - upload_start

        # Get file names for description
        file_names = [os.path.basename(f) for f in test_files]

        if task_id:
            self._task_id = task_id
            self.add_test_result(
                self._test_upload_file_types.test_number,
                self._test_upload_file_types.test_name,
                f"Upload various file types to test file type support. Collection: {self.TEST_FILE_TYPES_COLLECTION}. Files: {', '.join(file_names)}. Non-blocking mode with summary generation disabled.",
                ["POST /v1/documents"],
                [
                    "collection_name",
                    "blocking",
                    "generate_summary",
                    "split_options",
                ],
                upload_time,
                TestStatus.SUCCESS,
            )
            return True
        else:
            self.add_test_result(
                self._test_upload_file_types.test_number,
                self._test_upload_file_types.test_name,
                f"Upload various file types to test file type support. Collection: {self.TEST_FILE_TYPES_COLLECTION}. Files: {', '.join(file_names)}. Non-blocking mode with summary generation disabled.",
                ["POST /v1/documents"],
                [
                    "collection_name",
                    "blocking",
                    "generate_summary",
                    "split_options",
                ],
                upload_time,
                TestStatus.FAILURE,
                "Failed to upload file type test documents",
            )
            return False

    @test_case(40, "Wait for File Type Ingestion Completion")
    async def _test_wait_for_file_type_ingestion(self) -> bool:
        """Test waiting for file type ingestion completion"""
        logger.info("\n=== Test 40: Wait for File Type Ingestion Completion ===")
        wait_start = time.time()

        if not self._task_id:
            self.add_test_result(
                self._test_wait_for_file_type_ingestion.test_number,
                self._test_wait_for_file_type_ingestion.test_name,
                f"Wait for file type ingestion completion using status API. Collection: {self.TEST_FILE_TYPES_COLLECTION}. Task ID: {self._task_id}. Polls /status endpoint until completion.",
                ["GET /v1/status"],
                ["task_id", "state", "progress"],
                time.time() - wait_start,
                TestStatus.FAILURE,
                "No task ID available for status checking",
            )
            return False

        ingestion_success = await self._wait_for_task_completion(self._task_id)
        wait_time = time.time() - wait_start

        if ingestion_success:
            self.add_test_result(
                self._test_wait_for_file_type_ingestion.test_number,
                self._test_wait_for_file_type_ingestion.test_name,
                f"Wait for file type ingestion completion using status API. Collection: {self.TEST_FILE_TYPES_COLLECTION}. Task ID: {self._task_id}. Polls /status endpoint until completion.",
                ["GET /v1/status"],
                ["task_id", "state", "progress"],
                wait_time,
                TestStatus.SUCCESS,
            )
            return True
        else:
            self.add_test_result(
                self._test_wait_for_file_type_ingestion.test_number,
                self._test_wait_for_file_type_ingestion.test_name,
                f"Wait for file type ingestion completion using status API. Collection: {self.TEST_FILE_TYPES_COLLECTION}. Task ID: {self._task_id}. Polls /status endpoint until completion.",
                ["GET /v1/status"],
                ["task_id", "state", "progress"],
                wait_time,
                TestStatus.FAILURE,
                "File type ingestion failed or timed out",
            )
            return False

    def _get_file_type_test_files(self) -> list[str]:
        """Get full file paths for file type test files"""
        test_files = []
        data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")

        for filename in self._file_type_test_files:
            file_path = os.path.join(data_dir, filename)
            if os.path.exists(file_path):
                test_files.append(file_path)
            else:
                logger.warning(f"⚠️ Test file not found: {file_path}")

        logger.info(
            f"📁 Found {len(test_files)} file type test files: {[os.path.basename(f) for f in test_files]}"
        )
        return test_files

    async def _upload_documents(
        self,
        collection_name: str,
        files: list[str],
        blocking: bool = False,
        custom_metadata: list[dict[str, Any]] = None,
        generate_summary: bool = False,
    ) -> str | None:
        """Upload documents to a collection"""
        data = {
            "collection_name": collection_name,
            "blocking": blocking,
            "split_options": {"chunk_size": 512, "chunk_overlap": 150},
            "custom_metadata": custom_metadata or [],
            "generate_summary": generate_summary,
        }

        form_data = aiohttp.FormData()
        for file_path in files:
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    file_content = f.read()
                form_data.add_field(
                    "documents",
                    file_content,
                    filename=os.path.basename(file_path),
                    content_type="application/octet-stream",
                )

        form_data.add_field("data", json.dumps(data), content_type="application/json")

        async with aiohttp.ClientSession() as session:
            try:
                logger.info(
                    f"📤 Uploading {len(files)} file type test documents to collection '{collection_name}'"
                )
                logger.info(f"📁 Files: {[os.path.basename(f) for f in files]}")
                logger.info(f"📋 Upload data: {json.dumps(data, indent=2)}")

                async with session.post(
                    f"{self.ingestor_server_url}/v1/documents", data=form_data
                ) as response:
                    result = await response.json()
                    if response.status == 200:
                        logger.info(
                            f"✅ Upload request successful. Response:\n{json.dumps(result, indent=2)}"
                        )
                        if blocking:
                            # For blocking uploads, the API returns completion result directly
                            total_documents = result.get("total_documents", 0)
                            failed_documents = result.get("failed_documents", [])
                            logger.info(
                                f"✅ Documents uploaded successfully (blocking). Total: {total_documents}, Failed: {len(failed_documents)}"
                            )
                            if failed_documents:
                                logger.warning(
                                    f"⚠️ Failed documents: {failed_documents}"
                                )
                            # Return a special value to indicate blocking completion
                            return "BLOCKING_COMPLETED"
                        else:
                            # For non-blocking uploads, return the task_id
                            task_id = result.get("task_id")
                            logger.info(
                                f"✅ Documents uploaded successfully. Task ID: {task_id}"
                            )
                            return task_id
                    else:
                        logger.error(
                            f"❌ Failed to upload documents. Status: {response.status}"
                        )
                        logger.error(f"❌ Response:\n{json.dumps(result, indent=2)}")
                        return None
            except Exception as e:
                logger.error(f"❌ Error uploading documents: {e}")
                return None

    async def _wait_for_task_completion(self, task_id: str) -> bool:
        """Wait for task completion by polling status endpoint"""
        start_time = time.time()

        while time.time() - start_time < self.timeout:
            async with aiohttp.ClientSession() as session:
                try:
                    params = {"task_id": task_id}
                    async with session.get(
                        f"{self.ingestor_server_url}/v1/status", params=params
                    ) as response:
                        result = await response.json()
                        if response.status == 200:
                            state = result.get("state")
                            if state == "FINISHED":
                                logger.info(f"✅ Task {task_id} completed successfully")
                                logger.info(
                                    f"Task result:\n{json.dumps(result, indent=2)}"
                                )

                                # Validate the FINISHED response structure
                                validation_success = self._validate_finished_response(
                                    result
                                )
                                if not validation_success:
                                    logger.error(
                                        "❌ FINISHED response validation failed"
                                    )
                                    return False

                                return True
                            elif state == "FAILED":
                                logger.error(f"❌ Task {task_id} failed")
                                logger.error(
                                    f"Task failure details:\n{json.dumps(result, indent=2)}"
                                )
                                return False
                            else:
                                logger.info(f"⏳ Task {task_id} state: {state}")
                                # Log additional task details for debugging
                                if "progress" in result:
                                    logger.info(
                                        f"   Progress: {result.get('progress')}"
                                    )
                                if "message" in result:
                                    logger.info(f"   Message: {result.get('message')}")

                except Exception as e:
                    logger.error(f"❌ Error checking task status: {e}")

            await asyncio.sleep(self.poll_interval)

        logger.error(f"❌ Task {task_id} timed out after {self.timeout} seconds")
        return False

    @test_case(50, "CSV Deletion Batch Processing Test")
    async def _test_csv_deletion_batch_processing(self) -> bool:
        """Test CSV deletion timing during batch processing"""
        logger.info("\n=== Test 50: CSV Deletion Batch Processing Test ===")
        start_time = time.time()

        # Get batch test files (20 files: 10 existing + 10 dummy)
        batch_test_files = self._get_batch_test_files()

        # Upload documents with batch processing
        task_id = await self._upload_documents_with_batch_processing(
            collection_name="test_csv_deletion_batch",
            files=batch_test_files,
            blocking=False,
            custom_metadata=[],
            generate_summary=False,
        )

        upload_time = time.time() - start_time

        if task_id:
            self._csv_batch_task_id = task_id
            self.add_test_result(
                self._test_csv_deletion_batch_processing.test_number,
                self._test_csv_deletion_batch_processing.test_name,
                "Test CSV deletion timing during batch processing with 20 files",
                ["POST /v1/documents"],
                ["collection_name", "blocking", "generate_summary", "split_options"],
                upload_time,
                TestStatus.SUCCESS,
            )
            return True
        else:
            self.add_test_result(
                self._test_csv_deletion_batch_processing.test_number,
                self._test_csv_deletion_batch_processing.test_name,
                "Test CSV deletion timing during batch processing with 20 files",
                ["POST /v1/documents"],
                ["collection_name", "blocking", "generate_summary", "split_options"],
                upload_time,
                TestStatus.FAILURE,
                "Failed to upload batch test documents",
            )
            return False

    @test_case(51, "Wait for CSV Deletion Batch Processing Completion")
    async def _test_wait_for_csv_batch_completion(self) -> bool:
        """Wait for CSV deletion batch processing completion"""
        logger.info(
            "\n=== Test 51: Wait for CSV Deletion Batch Processing Completion ==="
        )
        start_time = time.time()

        if not hasattr(self, "_csv_batch_task_id") or not self._csv_batch_task_id:
            logger.error("❌ No CSV batch task ID found")
            return False

        # Wait for task completion
        success = await self._wait_for_task_completion(self._csv_batch_task_id)
        completion_time = time.time() - start_time

        if success:
            self.add_test_result(
                self._test_wait_for_csv_batch_completion.test_number,
                self._test_wait_for_csv_batch_completion.test_name,
                "Wait for CSV deletion batch processing completion",
                ["GET /v1/status"],
                ["task_id", "state", "progress"],
                completion_time,
                TestStatus.SUCCESS,
            )
            return True
        else:
            self.add_test_result(
                self._test_wait_for_csv_batch_completion.test_number,
                self._test_wait_for_csv_batch_completion.test_name,
                "Wait for CSV deletion batch processing completion",
                ["GET /v1/status"],
                ["task_id", "state", "progress"],
                completion_time,
                TestStatus.FAILURE,
                "CSV deletion batch processing failed or timed out",
            )
            return False

    def _get_batch_test_files(self) -> list[str]:
        """Get 20 files for batch processing test (10 existing + 10 dummy files)"""
        # Get existing 10 files
        existing_files = self._get_file_type_test_files()

        # Create 10 dummy text files in memory to make it 20 total (will trigger 2 batches: 16 + 4)
        dummy_files = []
        for i in range(1, 11):
            dummy_files.append(f"__tmp__/dummy_csv_test_{i}.txt")

        # Combine existing and dummy files
        all_files = existing_files + dummy_files
        logger.info(
            f"📁 Batch test files: {len(existing_files)} existing + {len(dummy_files)} dummy = {len(all_files)} total (will create 2 batches: 16 + 4)"
        )
        return all_files

    async def _upload_documents_with_batch_processing(
        self,
        collection_name: str,
        files: list[str],
        blocking: bool = False,
        custom_metadata: list[dict[str, Any]] = None,
        generate_summary: bool = False,
    ) -> str | None:
        """Upload documents with batch processing enabled for CSV deletion testing"""
        data = {
            "collection_name": collection_name,
            "blocking": blocking,
            "split_options": {"chunk_size": 512, "chunk_overlap": 150},
            "custom_metadata": custom_metadata or [],
            "generate_summary": generate_summary,
        }

        form_data = aiohttp.FormData()

        # Handle both existing files and dummy files
        for file_path in files:
            if os.path.exists(file_path):
                # Existing file - read from disk
                with open(file_path, "rb") as f:
                    file_content = f.read()
                form_data.add_field(
                    "documents",
                    file_content,
                    filename=os.path.basename(file_path),
                    content_type="application/octet-stream",
                )
            else:
                # Dummy file - create content in memory
                dummy_content = f"Dummy file {file_path.split('_')[-1].split('.')[0]} for CSV deletion batch test."
                form_data.add_field(
                    "documents",
                    dummy_content.encode("utf-8"),
                    filename=file_path,
                    content_type="text/plain",
                )

        form_data.add_field("data", json.dumps(data), content_type="application/json")

        async with aiohttp.ClientSession() as session:
            try:
                logger.info(
                    f"📤 Uploading {len(files)} files for CSV deletion batch processing test to collection '{collection_name}'"
                )
                logger.info(
                    f"📁 Files: {[os.path.basename(f) for f in files[:5]]}... (20 total)"
                )
                logger.info(f"📋 Upload data: {json.dumps(data, indent=2)}")

                async with session.post(
                    f"{self.ingestor_server_url}/v1/documents", data=form_data
                ) as response:
                    result = await response.json()
                    if response.status == 200:
                        logger.info(
                            f"✅ Upload request successful. Response:\n{json.dumps(result, indent=2)}"
                        )
                        if blocking:
                            # For blocking uploads, the API returns completion result directly
                            total_documents = result.get("total_documents", 0)
                            failed_documents = result.get("failed_documents", [])
                            logger.info(
                                f"✅ Documents uploaded successfully (blocking). Total: {total_documents}, Failed: {len(failed_documents)}"
                            )
                            if failed_documents:
                                logger.warning(
                                    f"⚠️ Failed documents: {failed_documents}"
                                )
                            # Return a special value to indicate blocking completion
                            return "BLOCKING_COMPLETED"
                        else:
                            # For non-blocking uploads, return the task_id
                            task_id = result.get("task_id")
                            logger.info(
                                f"✅ Documents uploaded successfully. Task ID: {task_id}"
                            )
                            return task_id
                    else:
                        logger.error(
                            f"❌ Failed to upload documents. Status: {response.status}"
                        )
                        logger.error(f"❌ Response:\n{json.dumps(result, indent=2)}")
                        return None
            except Exception as e:
                logger.error(f"❌ Error uploading documents: {e}")
                return None

    def _validate_finished_response(self, response: dict) -> bool:
        """Validate the structure of FINISHED status response"""
        try:
            # Check top-level structure
            if "state" not in response or response["state"] != "FINISHED":
                logger.error("❌ Missing or incorrect 'state' field")
                return False

            if "result" not in response:
                logger.error("❌ Missing 'result' field in FINISHED response")
                return False

            result = response["result"]

            # Check required result fields
            required_fields = [
                "message",
                "total_documents",
                "documents",
                "failed_documents",
                "validation_errors",
            ]
            for field in required_fields:
                if field not in result:
                    logger.error(f"❌ Missing required field '{field}' in result")
                    return False

            # Validate message
            if not isinstance(result["message"], str):
                logger.error("❌ 'message' field should be a string")
                return False

            # Validate total_documents
            if not isinstance(result["total_documents"], int):
                logger.error("❌ 'total_documents' field should be an integer")
                return False

            # Validate documents array
            if not isinstance(result["documents"], list):
                logger.error("❌ 'documents' field should be a list")
                return False

            # Validate each document structure
            for i, doc in enumerate(result["documents"]):
                if not isinstance(doc, dict):
                    logger.error(f"❌ Document {i} should be a dict")
                    return False

                if "document_name" not in doc:
                    logger.error(f"❌ Document {i} missing 'document_name' field")
                    return False

                if "metadata" not in doc:
                    logger.error(f"❌ Document {i} missing 'metadata' field")
                    return False

                if not isinstance(doc["metadata"], dict):
                    logger.error(f"❌ Document {i} 'metadata' should be a dict")
                    return False

                # Check that metadata contains filename
                if "filename" not in doc["metadata"]:
                    logger.error(f"❌ Document {i} metadata missing 'filename' field")
                    return False

            # Validate failed_documents array
            if not isinstance(result["failed_documents"], list):
                logger.error("❌ 'failed_documents' field should be a list")
                return False

            # Validate each failed document structure
            for i, failed_doc in enumerate(result["failed_documents"]):
                if not isinstance(failed_doc, dict):
                    logger.error(f"❌ Failed document {i} should be a dict")
                    return False

                if "document_name" not in failed_doc:
                    logger.error(
                        f"❌ Failed document {i} missing 'document_name' field"
                    )
                    return False

                if "error_message" not in failed_doc:
                    logger.error(
                        f"❌ Failed document {i} missing 'error_message' field"
                    )
                    return False

            # Validate validation_errors array
            if not isinstance(result["validation_errors"], list):
                logger.error("❌ 'validation_errors' field should be a list")
                return False

            # Validate document counts based on actual files being uploaded
            # Check if this is the CSV deletion batch test (20 files) or regular file type test (10 files)
            if hasattr(self, "_csv_batch_task_id") and self._csv_batch_task_id:
                total_uploaded = (
                    20  # CSV deletion batch test: 10 existing + 10 dummy files
                )
            else:
                total_uploaded = len(
                    self._file_type_test_files
                )  # Regular file type test: 10 files

            logger.info(f"📊 Total uploaded files: {total_uploaded}")
            logger.info(
                f"📊 Actual successful: {result['total_documents']}, failed: {len(result['failed_documents'])}"
            )

            # Validate that total_documents represents all processed documents (successful + failed)
            actual_successful_count = len(result["documents"])
            actual_failed_count = len(result["failed_documents"])
            reported_total_documents = result["total_documents"]
            expected_total = actual_successful_count + actual_failed_count

            if reported_total_documents != expected_total:
                logger.error(
                    f"❌ Inconsistency: total_documents field says {reported_total_documents} but actual processed count is {expected_total} (successful: {actual_successful_count} + failed: {actual_failed_count})"
                )
                return False

            logger.info(
                f"✅ total_documents field correctly reports {reported_total_documents} total processed documents"
            )

            # The key validation: ensure we account for all uploaded files
            # total_documents should equal the number of files we uploaded
            if reported_total_documents != total_uploaded:
                logger.error(
                    f"❌ Total processed documents ({reported_total_documents}) doesn't match uploaded count ({total_uploaded})"
                )
                return False

            logger.info(
                f"✅ All {total_uploaded} uploaded files were processed (successful: {actual_successful_count} + failed: {actual_failed_count})"
            )

            # Log successful and failed documents for verification (but don't fail on specific counts)
            actual_doc_names = [doc["document_name"] for doc in result["documents"]]
            actual_failed_names = [
                doc["document_name"] for doc in result["failed_documents"]
            ]

            logger.info(f"✅ Successful documents: {sorted(actual_doc_names)}")
            logger.info(f"❌ Failed documents: {sorted(actual_failed_names)}")

            # GIF remains unsupported; CSV is converted to text for ingestion.
            expected_failed_files = {
                "India_population.gif": "Unsupported file type",
            }

            if "PdM_machines.csv" not in actual_doc_names:
                logger.error("CSV compatibility ingestion did not return PdM_machines.csv")
                return False

            failed_docs_dict = {
                doc["document_name"]: doc["error_message"]
                for doc in result["failed_documents"]
            }

            for expected_file, expected_error in expected_failed_files.items():
                if (
                    expected_file in self._file_type_test_files
                ):  # Only check if file was actually uploaded
                    if expected_file not in failed_docs_dict:
                        logger.error(
                            f"❌ Expected failed file '{expected_file}' not found in failed_documents"
                        )
                        return False

                    actual_error = failed_docs_dict[expected_file]
                    if expected_error not in actual_error:
                        logger.error(
                            f"❌ Expected error message for '{expected_file}' was '{expected_error}', but got '{actual_error}'"
                        )
                        return False

                    logger.info(
                        f"✅ File '{expected_file}' correctly failed with error: '{expected_error}'"
                    )

            # Validate that all uploaded files are accounted for
            all_processed_files = set(actual_doc_names + actual_failed_names)

            if hasattr(self, "_csv_batch_task_id") and self._csv_batch_task_id:
                uploaded_filenames = [
                    os.path.basename(f) for f in self._file_type_test_files
                ]  # 10 existing files
                dummy_filenames = [
                    f"__tmp__/dummy_csv_test_{i}.txt" for i in range(1, 11)
                ]  # 10 dummy files
                uploaded_files_set = set(uploaded_filenames + dummy_filenames)

                # Handle URL encoding in response filenames
                decoded_processed_files = set()
                for filename in all_processed_files:
                    decoded_filename = urllib.parse.unquote(filename)
                    decoded_processed_files.add(decoded_filename)

                if decoded_processed_files != uploaded_files_set:
                    missing_files = uploaded_files_set - decoded_processed_files
                    extra_files = decoded_processed_files - uploaded_files_set
                    if missing_files:
                        logger.error(f"❌ Missing files in response: {missing_files}")
                    if extra_files:
                        logger.error(f"❌ Extra files in response: {extra_files}")
                    return False
            else:
                uploaded_filenames = [
                    os.path.basename(f) for f in self._file_type_test_files
                ]
                uploaded_files_set = set(uploaded_filenames)

                if all_processed_files != uploaded_files_set:
                    missing_files = uploaded_files_set - all_processed_files
                    extra_files = all_processed_files - uploaded_files_set
                    if missing_files:
                        logger.error(f"❌ Missing files in response: {missing_files}")
                    if extra_files:
                        logger.error(f"❌ Extra files in response: {extra_files}")
                    return False

            if hasattr(self, "_csv_batch_task_id") and self._csv_batch_task_id:
                csv_validation_success = (
                    self._validate_csv_deletion_for_batch_processing(result)
                )
                if not csv_validation_success:
                    logger.error("❌ CSV deletion validation failed")
                    return False
                logger.info("✅ CSV deletion validation passed")

            logger.info("✅ FINISHED response structure validation passed")
            return True

        except Exception as e:
            logger.error(f"❌ Error validating FINISHED response: {e}")
            return False

    def _validate_csv_deletion_for_batch_processing(self, result: dict) -> bool:
        """Validate that CSV deletion happened correctly during batch processing"""
        try:
            logger.info("🔍 Validating CSV deletion timing for batch processing...")

            # Get the actual number of files that were uploaded
            batch_test_files = self._get_batch_test_files()
            total_uploaded = len(batch_test_files)
            actual_total = result.get("total_documents", 0)

            if actual_total != total_uploaded:
                logger.error(
                    f"❌ Expected {total_uploaded} documents, but got {actual_total}"
                )
                return False

            logger.info(
                f"✅ Document count validation passed: {actual_total} documents processed"
            )

            successful_count = len(result.get("documents", []))
            failed_count = len(result.get("failed_documents", []))

            if successful_count + failed_count != total_uploaded:
                logger.error(
                    f"❌ Document count mismatch: successful ({successful_count}) + failed ({failed_count}) != total ({total_uploaded})"
                )
                return False

            logger.info(
                f"✅ Document processing validation passed: {successful_count} successful, {failed_count} failed"
            )

            message = result.get("message", "")
            if "successfully completed" not in message.lower():
                logger.error(f"❌ Unexpected completion message: {message}")
                return False

            logger.info(f"✅ Batch processing completion validation passed: {message}")
            return True

        except Exception as e:
            logger.error(f"❌ Error validating CSV deletion for batch processing: {e}")
            return False
