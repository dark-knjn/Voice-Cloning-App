import os
import torch
from typing import Optional
from unidecode import unidecode

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "nvidia_alphabet.txt")) as f:
    NVIDIA_ALPHABET = f.read().splitlines()


def load_checkpoint(checkpoint_path, model, optimizer, train_loader):
    """
    Credit: https://github.com/NVIDIA/tacotron2

    Loads a given checkpoint to model & optimizer.

    Parameters
    ----------
    checkpoint_path : str
        Path to checkpoint
    model : Tacotron2
        tacotron2 model to load checkpoint into
    optimizer : torch.optim
        Torch optimizer
    train_loader: torch.Dataloader
        Torch training dataloader

    Returns
    -------
    Tacotron2
        Loaded tacotron2 model
    torch.optim
        Loaded optimizer
    int
        current iteration number
    """
    checkpoint_dict = torch.load(checkpoint_path, map_location="cpu")
    model.load_state_dict(checkpoint_dict["state_dict"])
    optimizer.load_state_dict(checkpoint_dict["optimizer"])
    iteration = checkpoint_dict["iteration"]
    epoch = checkpoint_dict.get("epoch", max(0, int(iteration / len(train_loader))))
    return model, optimizer, iteration, epoch


def transfer_symbols_embedding(
    original_embedding_weight: torch.Tensor, embedding_layer, new_symbols: list, original_symbols: Optional[list] = None
):
    """
    Transfer embedding information from transfer learning model to reduce embedding time.
    If symbol is not found it is initialised with mean/std.

    Parameters
    ----------
    original_embedding_weight : Torch.tensor
        Checkpoint embeddings
    embedding_layer : torch.nn.modules.sparse.Embedding
        Model embedding layer
    new_symbols : list
        list of text symbols used by the model currently loaded
    original_symbols : list (optional)
        list of symbols used by the checkpoint model (defaults to NVIDIA_ALPHABET)
    """
    if original_symbols is None:
        original_symbols = NVIDIA_ALPHABET
    assert (
        len(original_symbols) == original_embedding_weight.shape[0]
    ), f"length of original_symbols does not match length of checkpoint model embedding! Got {len(original_symbols)} and {original_embedding_weight.shape[0]}."

    weight_tensor = original_embedding_weight.data
    original_std = weight_tensor.std()
    original_mean = weight_tensor.mean()

    weight_dict = {}
    for symbol_index, symbol in enumerate(original_symbols):
        # save vector for each symbol into it's own key
        weight_dict[symbol] = weight_tensor[symbol_index]

    for symbol_index, new_symbol in enumerate(new_symbols):
        # transfers matching symbols from pretrained model to new model  e.g: 'e' -> 'e'
        if new_symbol in weight_dict:
            embedding_layer.weight.data[symbol_index] = weight_dict[new_symbol]

        # transfers non-ascii symbols from pretrained model to new model  e.g: 'e' -> 'é'
        elif unidecode(new_symbol) in weight_dict:
            embedding_layer.weight.data[symbol_index] = weight_dict[unidecode(new_symbol)]

        # transfers upper-case symbols from pretrained model to new model  e.g: 'E' -> 'e'
        elif new_symbol.upper() in weight_dict:
            embedding_layer.weight.data[symbol_index] = weight_dict[new_symbol.upper()]

        # transfers lower-case symbols from pretrained model to new model  e.g: 'e' -> 'E'
        elif new_symbol.lower() in weight_dict:
            embedding_layer.weight.data[symbol_index] = weight_dict[new_symbol.lower()]

        else:
            # if new_symbol doesn't exist in pretrained model
            # initialize new symbol with average mean+std of the pretrained embedding,
            # to ensure no large loss spikes when the new symbol is seen for the first time.
            embedding_layer.weight.data[symbol_index] = weight_tensor[0].clone().normal_(original_mean, original_std)


def warm_start_model(checkpoint_path, model, symbols=None, ignore_layers=["embedding.weight"]):
    """
    Credit: https://github.com/NVIDIA/tacotron2

    Warm start model for transfer learning.

    Parameters
    ----------
    checkpoint_path : str
        Path to checkpoint
    model : Tacotron2
        tacotron2 model to load checkpoint into
    ignore_layers : list (optional)
        list of layers to ignore (default is ["embedding.weight"])
    symbols : list
        list of text symbols used by the fresh model currently loaded

    Returns
    -------
    Tacotron2
        Loaded tacotron2 model
    """
    checkpoint_dict = torch.load(checkpoint_path, map_location="cpu")
    model_dict = checkpoint_dict["state_dict"]
    if ignore_layers:
        model_dict = {k: v for k, v in model_dict.items() if k not in ignore_layers}
        dummy_dict = model.state_dict()
        dummy_dict.update(model_dict)
        model_dict = dummy_dict
    model.load_state_dict(model_dict)

    # transfer embedding.weight manually to prevent size conflicts
    old_symbols = model_dict.get("symbols", None)
    if symbols is None:
        print("WARNING: called warm_start_model with symbols not set. This will be unsupported in the future.")
    if (
        symbols is not None
        and old_symbols != symbols
        and hasattr(model, "embedding")
        and "embedding.weight" in model_dict
    ):
        transfer_symbols_embedding(
            checkpoint_dict["state_dict"]["embedding.weight"], model.embedding, symbols, old_symbols
        )
    return model


def get_state_dict(model):
    """
    Gets state dict for a given tacotron2 model.
    Handles parallel & non-parallel model types.

    Parameters
    ----------
    model : Tacotron2
        tacotron2 model

    Returns
    -------
    dict
        Model state dict
    """
    if isinstance(model, torch.nn.DataParallel):
        return model.module.state_dict()
    else:
        return model.state_dict()


def save_checkpoint(
    model,
    optimizer,
    learning_rate,
    iteration,
    symbols,
    epoch,
    output_directory,
    checkpoint_frequency,
    checkpoint_backup_frequency,
):
    """
    Save training checkpoint.
    Calls checkpoint cleanup on completion.

    Parameters
    ----------
    model : Tacotron2
        tacotron2 model
    optimizer : torch.optim
        Torch optimizer
    learning_rate : float
        Learning rate
    iteration : int
        Current iteration
    symbols : list
        list of valid symbols for model input text
    epoch : int
        Current epoch
    output_directory : str
        Folder to save checkpoint to
    checkpoint_frequency : int
        Frequency of checkpoint creation (in iterations)
    checkpoint_backup_frequency : int
        Frequency of checkpoint backups (in iterations)
    """
    checkpoint_name = "checkpoint_{}".format(iteration)
    torch.save(
        {
            "iteration": iteration,
            "state_dict": get_state_dict(model),
            "optimizer": optimizer.state_dict(),
            "learning_rate": learning_rate,
            "epoch": epoch,
            "symbols": symbols,
        },
        os.path.join(output_directory, checkpoint_name),
    )
    checkpoint_cleanup(output_directory, iteration, checkpoint_frequency, checkpoint_backup_frequency)


def checkpoint_cleanup(output_directory, iteration, checkpoint_frequency, checkpoint_backup_frequency):
    """
    Deletes previous checkpoint if it should be kept as a backup

    Parameters
    ----------
    output_directory : str
        Checkpoint folder
    iteration : int
        Current iteration
    checkpoint_frequency : int
        Frequency of checkpoint creation (in iterations)
    checkpoint_backup_frequency : int
        Frequency of checkpoint backups (in iterations)
    """
    if iteration > 0:
        last_checkpoint = iteration - checkpoint_frequency
        if last_checkpoint % checkpoint_backup_frequency != 0:
            # Last checkpoint shouldn't be kept as a backup
            try:
                os.remove(os.path.join(output_directory, "checkpoint_{}".format(last_checkpoint)))
            except OSError:
                pass
