from datalad.customremotes import SpecialRemote
from datalad.customremotes.main import main as super_main
from pyDataverse.api import DataAccessApi
from pyDataverse.models import Datafile
import os
from requests import delete
from requests.auth import HTTPBasicAuth
from annexremote import ExportRemote
from datalad_dataverse.utils import (
    get_native_api,
)
import os

class DataverseRemote(ExportRemote):

    def __init__(self, *args):
        super().__init__(*args)
        self.configs['url'] = 'The Dataverse URL for the remote'
        self.configs['doi'] = 'DOI to the dataset'
        self._api = None

    def initremote(self):
        """
            Use this command to initialize a remote
            git annex initremote dv1 type=external externaltype=dataverse encryption=none
        """
        if self.annex.getconfig('url') is None or self.annex.getconfig('doi') is None:
            raise ValueError('url and doi must be specified')

        # check if instance is readable and authenticated
        resp = self.api.get_info_version()
        if resp.json()['status'] != 'OK':
            raise RuntimeError(f'Cannot connect to dataverse instance (status: {resp.json()["status"]})')

        # check if project with specified doi exists
        dv_ds = self.api.get_dataset(identifier=self.annex.getconfig('doi'))
        if not dv_ds.ok:
            raise RuntimeError("Cannot find dataset")

    @property
    def api(self):
        if self._api is None:
            # connect to dataverse instance
            self._api = get_native_api(
                baseurl=self.annex.getconfig('url'),
                token=os.environ["DATAVERSE_API_TOKEN"],
            )
        return self._api

    def prepare(self):
        # trigger API instance in order to get possibly auth/connection errors
        # right away
        self.api

    def checkpresent(self, key):
        dataset = self.api.get_dataset(identifier=self.annex.getconfig('doi'))

        datafiles = dataset.json()['data']['latestVersion']['files']
        if next((item for item in datafiles if item['dataFile']['filename'] == key), None):
            return True
        else:
            return False

    def checkpresentexport(self, key, remote_file):
        return self.checkpresent(remote_file)

    def transfer_store(self, key, local_file):
        ds_pid = self.annex.getconfig('doi')

        datafile = Datafile()
        datafile.set({'pid': ds_pid, 
                      'filename': key,
                      'directoryLabel': os.path.dirname(key),
                      'label': os.path.basename(key)})
        resp = self.api.upload_datafile(ds_pid, local_file, datafile.json())
        resp.raise_for_status()

    def transferexport_store(self, key, local_file, remote_file):
        self.transfer_store(remote_file, local_file)

    def transfer_retrieve(self, key, file):
        data_api = DataAccessApi(
            base_url=self.annex.getconfig('url'),
            api_token=os.environ["DATAVERSE_API_TOKEN"]
        )
        dataset = self.api.get_dataset(identifier=self.annex.getconfig('doi'))

        # http error handling
        dataset.raise_for_status()

        files_list = dataset.json()['data']['latestVersion']['files']

        # find the file we want to download
        file_id = None
        for current_file in files_list:
            filename = current_file['dataFile']['filename']
            if filename == key:
                file_id = current_file['dataFile']['id']
                break

        # error handling if file was not found on remote
        if file_id is None:
            raise ValueError(f"File {key} is unknown to remote")

        response = data_api.get_datafile(file_id)
        # http error handling
        response.raise_for_status()
        with open(file, "wb") as f:
            f.write(response.content)

    def transferexport_retrieve(self, key, local_file, remote_file):
        self.transfer_retrieve(remote_file, local_file)

    def remove(self, key):
        # get the dataset and a list of all files
        dataset = self.api.get_dataset(identifier=self.annex.getconfig('doi'))
        # http error handling
        dataset.raise_for_status()
        files_list = dataset.json()['data']['latestVersion']['files']

        file_id = None

        # find the file we want to delete
        for file in files_list:
            filename = file['dataFile']['filename']
            if filename == key:
                file_id = file['dataFile']['id']
                break

        if file_id is None:
            # the key is not present, we can return, protocol
            # declare this condition to be a successful removal
            return

        # delete the file
        status = delete(f'{self.annex.getconfig("url")}/dvn/api/data-deposit/v1.1/swordv2/edit-media/file/{file_id}', 
                        auth=HTTPBasicAuth(os.environ["DATAVERSE_API_TOKEN"], ''))
        # http error handling
        status.raise_for_status()
    
    def removeexport(self, key, remote_file):
        return self.remove(remote_file)


def main():
    """cmdline entry point"""
    super_main(
        cls=DataverseRemote,
        remote_name='dataverse',
        description=\
        "transport file content to and from a Dataverse dataset",
)
