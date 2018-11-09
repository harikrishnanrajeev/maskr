import torch
import torch.nn.functional as F
from maskmm.tracker import saveall
import logging
log = logging.getLogger()

def squash(x):
    """ remove batch dimension """

    return x.view(-1, *x.shape[2:])

@saveall
def rpn_class(rpn_match, rpn_class_logits):
    """RPN anchor classifier loss.

    rpn_match: [batch, anchors, 1]. Anchor match type. 1=positive,
               -1=negative, 0=neutral anchor.
    rpn_class_logits: [batch, anchors, 2]. RPN classifier logits for FG/BG.
    """
    rpn_match = squash(rpn_match)
    rpn_class_logits = squash(rpn_class_logits)

    # Get anchor classes. Convert the -1/+1 match to 0/1 values.
    anchor_class = (rpn_match == 1).long()

    # Positive and Negative anchors contribute to the loss,
    # but neutral anchors (match value = 0) don't.
    indices = rpn_match.ne(0).nonzero()

    # Pick rows that contribute to the loss and filter out the rest.
    rpn_class_logits = rpn_class_logits[indices[:, 0], indices[:, 1]]
    anchor_class = anchor_class[indices[:, 0], indices[:, 1]]

    # Crossentropy loss
    loss = F.cross_entropy(rpn_class_logits, anchor_class)
    return loss

@saveall
def rpn_bbox(target_bbox, rpn_match, rpn_bbox):
    """Return the RPN bounding box loss

    target_bbox: [batch, max positive anchors, (dy, dx, log(dh), log(dw))].
        Uses 0 padding to fill in unsed bbox deltas.
    rpn_match: [batch, anchors, 1]. Anchor match type. 1=positive,
               -1=negative, 0=neutral anchor.
    rpn_bbox: [batch, anchors, (dy, dx, log(dh), log(dw))]
    """
    # Positive anchors contribute to the loss, but negative and
    # neutral anchors (match value of 0 or -1) don't.
    target_bbox = squash(target_bbox)
    rpn_match = squash(rpn_match)
    rpn_bbox = squash(rpn_bbox)

    indices = rpn_match.eq(1).nonzero()

    # Pick bbox deltas that contribute to the loss
    rpn_bbox = rpn_bbox[indices[:, 0], indices[:, 1]]

    # Trim target bounding box deltas to the same length as rpn_bbox.
    item_counts = rpn_match.eq(1).sum(dim=1)
    trimmed = []
    for i, count in enumerate(item_counts):
        trimmed.append(target_bbox[i, :count])
    target_bbox = torch.cat(trimmed)

    # Smooth L1 loss
    loss = F.smooth_l1_loss(rpn_bbox, target_bbox)

    return loss

@saveall
def mrcnn_class(target_class_ids, pred_class_logits):
    """Loss for the classifier head of Mask RCNN.

    target_class_ids: [batch, num_rois]. Integer class IDs. Uses zero
        padding to fill in the array.
    pred_class_logits: [batch, num_rois, num_classes]
    """
    pred_class_logits = squash(pred_class_logits)
    target_class_ids = squash(target_class_ids)
    # todo align sizes and comments in this file e.g. 2 images/batch => 138 ROIS
    if len(target_class_ids):
        loss = F.cross_entropy(pred_class_logits, target_class_ids.long())
    else:
        with torch.no_grad():
            loss = torch.tensor([0]).float()
    return loss

@saveall
def mrcnn_bbox(target_bbox, target_class_ids, pred_bbox):
    """Loss for Mask R-CNN bounding box refinement.

    target_bbox: [batch, num_rois, (dy, dx, log(dh), log(dw))]
    target_class_ids: [batch, num_rois]. Integer class IDs.
    pred_bbox: [batch, num_rois, num_classes, (dy, dx, log(dh), log(dw))]
    """
    target_bbox = squash(target_bbox)
    target_class_ids = squash(target_class_ids)
    pred_bbox = squash(pred_bbox)

    if len(target_class_ids):
        # Only positive ROIs contribute to the loss. And only
        # the right class_id of each ROI. Get their indicies.
        positive_roi_ix = torch.nonzero(target_class_ids > 0)[:, 0]
        positive_roi_class_ids = target_class_ids[positive_roi_ix].long()
        indices = torch.stack((positive_roi_ix, positive_roi_class_ids), dim=1)

        # Gather the deltas (predicted and true) that contribute to loss
        target_bbox = target_bbox[indices[:, 0], :]
        pred_bbox = pred_bbox[indices[:, 0], indices[:, 1], :]

        # Smooth L1 loss
        loss = F.smooth_l1_loss(pred_bbox, target_bbox)
    else:
        with torch.no_grad():
            loss = torch.tensor([0]).float()

    return loss

@saveall
def mrcnn_mask(target_masks, target_class_ids, pred_masks):
    """Mask binary cross-entropy loss for the masks head.

    target_masks: [batch, num_rois, height, width].
        A float32 tensor of values 0 or 1. Uses zero padding to fill array.
    target_class_ids: [batch, num_rois]. Integer class IDs. Zero padded.
    pred_masks: [batch, proposals, height, width, num_classes] float32 tensor
                with values from 0 to 1.
    """
    target_masks = squash(target_masks)
    target_class_ids = squash(target_class_ids)
    pred_masks = squash(pred_masks)

    if len(target_class_ids):
        # Only positive ROIs contribute to the loss. And only
        # the class specific mask of each ROI.
        positive_ix = torch.nonzero(target_class_ids > 0)[:, 0]
        positive_class_ids = target_class_ids[positive_ix].long()
        indices = torch.stack((positive_ix, positive_class_ids), dim=1)

        # Gather the masks (predicted and true) that contribute to loss
        y_true = target_masks[indices[:, 0], :, :]
        y_pred = pred_masks[indices[:, 0], indices[:, 1], :, :]

        # Binary cross entropy
        loss = F.binary_cross_entropy(y_pred, y_true)
    else:
        with torch.no_grad():
            loss = torch.tensor([0]).float()

    return loss
