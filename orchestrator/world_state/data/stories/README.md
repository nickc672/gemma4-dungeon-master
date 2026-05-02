# Story Library

Each story is a stable world-model folder under this directory. A folder is loadable by the Streamlit app when it contains:

- `story.json`
- `locations.json`
- `actors.json`
- `items.json`

The folder name is used as the story id. The Streamlit app lists these folders in the Story dropdown and passes the selected folder into the story engine as its `world_model_data_dir`.
